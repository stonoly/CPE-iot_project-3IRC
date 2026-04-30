package fr.cpe.miniarchi;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;

public class MainActivity extends AppCompatActivity {

    private static final String TAG = "IoT_App";

    private EditText ipEditText, portEditText, configEditText;
    private TextView receivedDataTextView;
    private Button connectButton, sendConfigButton, refreshButton;

    private final BlockingQueue<String> networkQueue = new LinkedBlockingQueue<>();
    private NetworkThread threadNetwork;
    private NetworkReceiveThread networkReceiveThread;
    private DatagramSocket UDPSocket;

    private boolean isListening = false;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private final NetworkReceiveThread.MyThreadEventListener listener =
            new NetworkReceiveThread.MyThreadEventListener() {
                @Override
                public void onEventInMyThread(String data) {
                    mainHandler.post(() -> receivedDataTextView.setText(data));
                }
            };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);

        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });

        ipEditText = findViewById(R.id.ipEditText);
        portEditText = findViewById(R.id.portEditText);
        receivedDataTextView = findViewById(R.id.receivedDataTextView);
        configEditText = findViewById(R.id.configEditText);
        connectButton = findViewById(R.id.connectButton);
        sendConfigButton = findViewById(R.id.sendConfigButton);
        refreshButton = findViewById(R.id.refreshButton);

        connectButton.setOnClickListener(v -> toggleListening());

        sendConfigButton.setOnClickListener(v -> {
            String config = configEditText.getText().toString().trim();
            if (!config.isEmpty()) {
                sendUDP(config);
            } else {
                Toast.makeText(this, R.string.msg_config_empty, Toast.LENGTH_SHORT).show();
            }
        });

        refreshButton.setOnClickListener(v -> sendUDP("getValues()"));
    }

    private void toggleListening() {
        if (!isListening) {
            startListening();
        } else {
            stopListening();
        }
    }

    private void startListening() {
        String portStr = portEditText.getText().toString().trim();
        if (portStr.isEmpty()) {
            Toast.makeText(this, R.string.msg_missing_fields, Toast.LENGTH_SHORT).show();
            return;
        }

        int port;
        try {
            port = Integer.parseInt(portStr);
        } catch (NumberFormatException e) {
            Toast.makeText(this, R.string.msg_missing_fields, Toast.LENGTH_SHORT).show();
            return;
        }

        try {
            UDPSocket = new DatagramSocket(null);
            UDPSocket.setReuseAddress(true);
            UDPSocket.bind(new InetSocketAddress(InetAddress.getByName("0.0.0.0"), port));
        } catch (Exception e) {
            Log.e(TAG, "Impossible d'ouvrir le socket UDP", e);
            Toast.makeText(this, getString(R.string.msg_error_rx, e.getMessage()),
                    Toast.LENGTH_SHORT).show();
            return;
        }

        threadNetwork = new NetworkThread(networkQueue, UDPSocket);
        networkReceiveThread = new NetworkReceiveThread(UDPSocket, listener);
        threadNetwork.start();
        networkReceiveThread.start();

        isListening = true;
        connectButton.setText(R.string.btn_stop_rx);
        Log.d(TAG, "Écoute UDP démarrée sur le port " + port);
    }

    private void stopListening() {
        isListening = false;

        if (threadNetwork != null) {
            threadNetwork.interrupt();
            threadNetwork = null;
        }

        if (UDPSocket != null && !UDPSocket.isClosed()) {
            UDPSocket.close();
        }
        UDPSocket = null;

        networkReceiveThread = null;
        connectButton.setText(R.string.btn_start_rx);
        Log.d(TAG, "Écoute UDP arrêtée");
    }

    private void sendUDP(String message) {
        String ip = ipEditText.getText().toString().trim();
        String portStr = portEditText.getText().toString().trim();

        if (ip.isEmpty() || portStr.isEmpty()) {
            Toast.makeText(this, R.string.msg_missing_fields, Toast.LENGTH_SHORT).show();
            return;
        }

        if (!isListening || threadNetwork == null) {
            Toast.makeText(this, R.string.msg_not_listening, Toast.LENGTH_SHORT).show();
            return;
        }

        new Thread(() -> {
            try {
                InetAddress address = InetAddress.getByName(ip);
                if (!(address instanceof Inet4Address)) {
                    mainHandler.post(() -> Toast.makeText(MainActivity.this,
                            "L'adresse doit être IPv4", Toast.LENGTH_SHORT).show());
                    return;
                }

                networkQueue.add(ip + ":" + portStr + ":" + message);

                mainHandler.post(() -> Toast.makeText(MainActivity.this,
                        getString(R.string.msg_sent, message), Toast.LENGTH_SHORT).show());
            } catch (Exception e) {
                Log.e(TAG, "Erreur de résolution IP", e);
                mainHandler.post(() -> Toast.makeText(MainActivity.this,
                        getString(R.string.msg_error_send, e.getMessage()),
                        Toast.LENGTH_SHORT).show());
            }
        }).start();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        stopListening();
    }
}
