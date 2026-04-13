#include "MicroBit.h"
#include "ssd1306.h"
#include "bme280.h"

MicroBit uBit;
MicroBitI2C i2c(I2C_SDA0, I2C_SCL0);
MicroBitPin P0(MICROBIT_ID_IO_P0, MICROBIT_PIN_P0, PIN_CAPABILITY_DIGITAL_OUT);

ManagedString mode = "THP";

void onData(MicroBitEvent)
{
    ManagedString msg = uBit.radio.datagram.recv();
    if (msg.length() > 0)
    {
        ManagedString newMode = "";
        for (int i = 0; i < msg.length(); i++)
        {
            char c = msg.charAt(i);
            if (c == 'T' || c == 'H' || c == 'P')
            {
                newMode = newMode + ManagedString(c);
            }
        }
        if (newMode.length() > 0)
        {
            mode = newMode;
        }
    }
}

int main()
{
    uBit.init();
    uBit.radio.enable();
    uBit.radio.setGroup(43);
    uBit.messageBus.listen(MICROBIT_ID_RADIO, MICROBIT_RADIO_EVT_DATAGRAM, onData);

    ssd1306 screen(&uBit, &i2c, &P0);
    bme280 bme(&uBit, &i2c);

    uint32_t pressure = 0;
    int32_t temp = 0;
    uint16_t humidite = 0;

    while (true)
    {
        bme.sensor_read(&pressure, &temp, &humidite);
        int tmp  = bme.compensate_temperature(temp) / 100;
        int pres = bme.compensate_pressure(pressure) / 100;
        int hum  = bme.compensate_humidity(humidite) / 100;

        // Envoi radio
        char msg[64];
        snprintf(msg, sizeof(msg), "%d;%d;%d", tmp, pres, hum);
        uBit.radio.datagram.send(msg);

        // Affichage selon le mode actif
        screen.clear();
        int line = 0;
        for (int i = 0; i < mode.length(); i++)
        {
            char buf[20];
            switch (mode.charAt(i))
            {
                case 'T':
                    snprintf(buf, sizeof(buf), "Temp:%dC", tmp);
                    screen.display_line(line++, 0, buf);
                    break;
                case 'H':
                    snprintf(buf, sizeof(buf), "Hum:%d%%", hum);
                    screen.display_line(line++, 0, buf);
                    break;
                case 'P':
                    snprintf(buf, sizeof(buf), "Pres:%dhPa", pres);
                    screen.display_line(line++, 0, buf);
                    break;
            }
        }

        screen.update_screen();
        uBit.sleep(1000);
    }

    release_fiber();
}