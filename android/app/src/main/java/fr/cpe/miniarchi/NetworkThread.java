package fr.cpe.miniarchi;

import android.util.Log;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.BlockingQueue;

public class NetworkThread extends Thread {

    private static final String TAG = "NetworkThread";

    private final BlockingQueue<String> queue;
    private final DatagramSocket UDPSocket;

    public NetworkThread(BlockingQueue<String> queue, DatagramSocket UDPSocket) {
        this.queue = queue;
        this.UDPSocket = UDPSocket;
    }

    @Override
    public void run() {
        try {
            while (!isInterrupted()) {
                String rawData = queue.take();

                String[] parts = rawData.split(":", 3);
                if (parts.length < 3) {
                    Log.w(TAG, "Format invalide (attendu ip:port:message) : " + rawData);
                    continue;
                }

                String targetIP = parts[0];
                int port = Integer.parseInt(parts[1]);
                String message = parts[2];

                InetAddress address = InetAddress.getByName(targetIP);
                byte[] data = message.getBytes(StandardCharsets.UTF_8);

                DatagramPacket packet = new DatagramPacket(data, data.length, address, port);
                UDPSocket.send(packet);

                Log.d(TAG, "Envoyé vers " + targetIP + ":" + port + " → " + message);
            }
        } catch (InterruptedException e) {
            Log.d(TAG, "Thread d'envoi interrompu, arrêt propre.");
            Thread.currentThread().interrupt();
        } catch (IOException e) {
            Log.e(TAG, "Erreur d'envoi UDP", e);
        } finally {
            if (UDPSocket != null && !UDPSocket.isClosed()) {
                UDPSocket.close();
            }
        }
    }
}
