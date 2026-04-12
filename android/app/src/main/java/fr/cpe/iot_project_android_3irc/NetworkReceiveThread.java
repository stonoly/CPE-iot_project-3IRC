package fr.cpe.iot_project_android_3irc;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.SocketException;
import java.net.UnknownHostException;

public class NetworkReceiveThread extends Thread {
    private DatagramSocket UDPSocket;

    // --- AJOUT SELON TON COURS ---
    public interface MyThreadEventListener {
        void onEventInMyThread(String data);
    }
    private MyThreadEventListener listener;

    // Constructeur mis à jour pour accepter le listener
    public NetworkReceiveThread(DatagramSocket UDPSocket, MyThreadEventListener listener) {
        this.UDPSocket = UDPSocket;
        this.listener = listener;
    }
    // ------------------------------

    public void run() {
        try {
            while (true) {
                byte[] data = new byte[1024];
                DatagramPacket packet = new DatagramPacket(data, data.length);
                UDPSocket.receive(packet);

                // Nettoyage de la chaîne reçue
                String log = new String(packet.getData(), 0, packet.getLength()).trim();
                android.util.Log.d("Receive", log);

                listener.onEventInMyThread(log);
            }
        } catch (SocketException e) {
            e.printStackTrace();
        } catch (UnknownHostException e) {
            throw new RuntimeException(e);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
    }
}