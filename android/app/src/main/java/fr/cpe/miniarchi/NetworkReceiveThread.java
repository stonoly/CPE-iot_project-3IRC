package fr.cpe.miniarchi;

import android.util.Log;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.SocketException;
import java.nio.charset.StandardCharsets;

public class NetworkReceiveThread extends Thread {

    private static final String TAG = "NetworkReceiveThread";

    public interface MyThreadEventListener {
        void onEventInMyThread(String data);
    }

    private final DatagramSocket UDPSocket;
    private final MyThreadEventListener listener;

    public NetworkReceiveThread(DatagramSocket UDPSocket, MyThreadEventListener listener) {
        this.UDPSocket = UDPSocket;
        this.listener = listener;
    }

    @Override
    public void run() {
        byte[] buffer = new byte[1024];
        try {
            while (!isInterrupted()) {
                DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
                UDPSocket.receive(packet);

                String received = new String(
                        packet.getData(),
                        0,
                        packet.getLength(),
                        StandardCharsets.UTF_8
                ).trim();

                Log.d(TAG, "Reçu : " + received);

                if (listener != null) {
                    listener.onEventInMyThread(received);
                }
            }
        } catch (SocketException e) {
            Log.d(TAG, "Socket fermée, fin du thread de réception.");
        } catch (IOException e) {
            Log.e(TAG, "Erreur de réception UDP", e);
        }
    }
}
