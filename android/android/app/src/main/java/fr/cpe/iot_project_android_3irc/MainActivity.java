package fr.cpe.iot_project_android_3irc;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.button.MaterialButtonToggleGroup;
import com.google.android.material.textfield.TextInputEditText;

import java.net.DatagramSocket;
import java.net.SocketException;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;

public class MainActivity extends AppCompatActivity {

    private BlockingQueue<String> networkQueue = new LinkedBlockingQueue<>();
    private NetworkThread threadNetwork;
    private NetworkReceiveThread networkReceiveThread;


    NetworkReceiveThread.MyThreadEventListener listener = new NetworkReceiveThread.MyThreadEventListener() {
        @Override
        public void onEventInMyThread(String data) {
            // Obligatoire pour toucher à l'interface graphique :
            String cleanData = data.trim();
            new Handler(Looper.getMainLooper()).post(new Runnable() {
                @Override
                public void run() {
                    if (cleanData.contains("1")) {
                        // Cas GAGNÉ
                        showResultModal("Résultat", "Bravo ! Vous avez GAGNÉ ! 🏆");
                    }
                    else if (cleanData.contains("0")) {
                        // Cas PERDU
                        showResultModal("Résultat", "Dommage... Vous avez PERDU. 💀");
                    }
                }
            });
        }
    };

    private void showResultModal(String title, String message) {
        new androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle(title)
                .setMessage(message)
                .setPositiveButton("OK", (dialog, which) -> {
                    dialog.dismiss();
                })
                .setCancelable(false)
                .show();
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        //Initialisation
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });

        DatagramSocket UDPSocket= null;
        try {
            UDPSocket = new DatagramSocket(10000);
        } catch (SocketException e) {
            throw new RuntimeException(e);
        }
        // Mon code
        threadNetwork= new NetworkThread(networkQueue, UDPSocket);
        networkReceiveThread= new NetworkReceiveThread(UDPSocket, listener);
        threadNetwork.start();
        networkReceiveThread.start();

        String[] valueToSend = {"(1)"};


        MaterialButtonToggleGroup toggleGroup = findViewById(R.id.toggleButton);
        MaterialButton btnBlue = findViewById(R.id.btn_blue);
        MaterialButton btnRed = findViewById(R.id.btn_red);

        Button bt_reset = findViewById(R.id.button_reset);
        Button bt_play = findViewById(R.id.button_play);

        TextInputEditText editIp = findViewById(R.id.edit_ip);
        TextInputEditText editPort = findViewById(R.id.edit_port);

        btnBlue.setAlpha(1.0f);
        btnRed.setAlpha(0.4f);

        toggleGroup.addOnButtonCheckedListener((group, checkedId, isChecked) -> {
            if (isChecked) {
                if (checkedId == R.id.btn_blue) {
                    btnBlue.setAlpha(1.0f);
                    btnRed.setAlpha(0.4f);
                    valueToSend[0] = "(1)";
                } else if (checkedId == R.id.btn_red) {
                    btnRed.setAlpha(1.0f);
                    btnBlue.setAlpha(0.4f);
                    valueToSend[0] = "(2)";
                }
            }
        });


        bt_play.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                String ip = editIp.getText().toString();
                String port = editPort.getText().toString();
                String cmd = valueToSend[0];
                networkQueue.add(ip + ":" + port + ":" + cmd);
            }
        });

        bt_reset.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                String ip = editIp.getText().toString();
                String port = editPort.getText().toString();
                String cmd = "(0)";
                networkQueue.add(ip + ":" + port + ":" + cmd);
            }
        });
    }
}