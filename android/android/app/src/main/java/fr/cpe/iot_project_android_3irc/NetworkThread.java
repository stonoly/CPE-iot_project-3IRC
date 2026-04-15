package fr.cpe.iot_project_android_3irc;

import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.util.concurrent.BlockingQueue;

public class NetworkThread extends Thread{
    private BlockingQueue<String> queue;
    private int PORT;
    private InetAddress address;
    private DatagramSocket UDPSocket;

    public NetworkThread(BlockingQueue<String> queue, DatagramSocket UDPSocket) {
        this.queue = queue;
        this.UDPSocket = UDPSocket;
    }
    public void run() {
        try {

            while(true) {
                String rawData = queue.take();
                String[] parts = rawData.split(":");

                String targetIP = parts[0];
                PORT = Integer.parseInt(parts[1]);
                String message = parts[2];

                address= InetAddress.getByName(targetIP);
                byte[] data= message.getBytes();
                DatagramPacket packet= new DatagramPacket(data,data.length, address, PORT);
                UDPSocket.send(packet);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (IOException e) {
            e.printStackTrace();
        } finally {
            if (UDPSocket != null) UDPSocket.close();
        }
    }

}