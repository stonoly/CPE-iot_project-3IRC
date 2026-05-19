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

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends AppCompatActivity {

    private static final String TAG = "IoT_App";
    private EditText ipEditText, portEditText, configEditText;
    private TextView receivedDataTextView;
    private Button connectButton, sendConfigButton, refreshButton;

    private DatagramSocket rxSocket;
    private boolean isListening = false;
    private final ExecutorService executorService = Executors.newFixedThreadPool(2);
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

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
        String portStr = portEditText.getText().toString();
        if (portStr.isEmpty()) {
            Toast.makeText(this, R.string.msg_missing_fields, Toast.LENGTH_SHORT).show();
            return;
        }

        int port = Integer.parseInt(portStr);
        isListening = true;
        connectButton.setText(R.string.btn_stop_rx);

        executorService.execute(() -> {
            try {
                // Forçage IPv4 pour l'écoute
                rxSocket = new DatagramSocket(null);
                rxSocket.setReuseAddress(true);
                rxSocket.bind(new InetSocketAddress(InetAddress.getByName("0.0.0.0"), port));

                byte[] buffer = new byte[2048];
                Log.d(TAG, "Démarrage écoute UDP IPv4 sur port " + port);

                while (isListening) {
                    DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
                    rxSocket.receive(packet);
                    String message = new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8);

                    mainHandler.post(() -> receivedDataTextView.setText(message));
                }
            } catch (Exception e) {
                if (isListening) {
                    Log.e(TAG, "Erreur de réception UDP", e);
                    mainHandler.post(() -> Toast.makeText(MainActivity.this,
                        getString(R.string.msg_error_rx, e.getMessage()), Toast.LENGTH_SHORT).show());
                }
            } finally {
                if (rxSocket != null && !rxSocket.isClosed()) {
                    rxSocket.close();
                }
            }
        });
    }

    private void stopListening() {
        isListening = false;
        if (rxSocket != null) {
            rxSocket.close();
        }
        connectButton.setText(R.string.btn_start_rx);
    }

    private void sendUDP(String message) {
        String ip = ipEditText.getText().toString().trim();
        String portStr = portEditText.getText().toString().trim();

        if (ip.isEmpty() || portStr.isEmpty()) {
            Toast.makeText(this, R.string.msg_missing_fields, Toast.LENGTH_SHORT).show();
            return;
        }

        int port = Integer.parseInt(portStr);

        executorService.execute(() -> {
            try {
                // Validation et forçage IPv4 pour l'envoi
                InetAddress address = InetAddress.getByName(ip);
                if (!(address instanceof Inet4Address)) {
                    mainHandler.post(() -> Toast.makeText(MainActivity.this, "L'adresse doit être IPv4", Toast.LENGTH_SHORT).show());
                    return;
                }

                byte[] data = message.getBytes(StandardCharsets.UTF_8);

                try (DatagramSocket socket = new DatagramSocket()) {
                    DatagramPacket packet = new DatagramPacket(data, data.length, address, port);
                    socket.send(packet);
                    Log.d(TAG, "UDP envoyé vers " + address.getHostAddress() + ":" + port);

                    mainHandler.post(() -> Toast.makeText(MainActivity.this,
                        getString(R.string.msg_sent, message), Toast.LENGTH_SHORT).show());
                }
            } catch (Exception e) {
                Log.e(TAG, "Erreur d'envoi UDP", e);
                mainHandler.post(() -> Toast.makeText(MainActivity.this,
                    getString(R.string.msg_error_send, e.getMessage()), Toast.LENGTH_SHORT).show());
            }
        });
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        stopListening();
        executorService.shutdownNow();
    }
}
