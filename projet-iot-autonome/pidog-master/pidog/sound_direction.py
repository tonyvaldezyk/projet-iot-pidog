#!/usr/bin/env python3
'''
                声音方位识别模块 通讯协议

1.通讯格式: master 随机发送16bit数据给slave,然后接收16bit数据
主控接收的16BIT 格式：
    (1) 先接收数据的低8bit,然后接收数据的高8bit
    (2) 遵从MSB传送

2.方向可以侦测360度方向,最小单位是20度。则数据范围为0~355.

3. 流程,主控拉高busy,064B(TR16F064B)开始监测方向。
   当064B识别到方向的时候,会拉低busy线(平时为高);主控监测到BUSY拉低,发16bit任意数据给064B,
   并接受16bit数据,接受完成后,主控把busy线拉高,再次检测方向.


        Sound Location Recognition Module Communication Protocol

1. Communication format: master randomly sends 16bit data to slave, and then receives 16bit data
16BIT format received by the master:
     (1) First receive the lower 8 bits of the data, and then receive the upper 8 bits of the data
     (2) Comply with MSB transmission

2. The direction can detect 360 degree direction, the minimum unit is 20 degrees. The data range is 0~355.

3. In the process, the master pulls up busy, and 064B (TR16F064B) starts to monitor the direction.
    When 064B recognizes the direction, it will pull down the busy line (usually high); the master monitors that BUSY is pulled low, and sends 16bit arbitrary data to 064B,
    And accept 16bit data, after the acceptance is completed, the main control pulls up the busy line and detects the direction again.

'''

import spidev
from gpiozero import OutputDevice, InputDevice


class SoundDirection():
    CS_DELAY_US = 500  # Mhz
    CLOCK_SPEED = 10000000  # 10 MHz

    def __init__(self, busy_pin=6):
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        #
        self.busy = InputDevice(busy_pin, pull_up=False)

    def read(self):
        result = self.spi.xfer2([0, 0, 0, 0, 0, 0], self.CLOCK_SPEED,
                                self.CS_DELAY_US)


        l_val, h_val = result[4:]  # ignore the fist two values
        # print([h_val, l_val])
        if h_val == 255:
            return -1
        else:
            val = (h_val << 8) + l_val
            val = (360 + 160 - val) % 360  # Convert zero
            return val

    def isdetected(self):
        return self.busy.value == 0


if __name__ == '__main__':
    from time import sleep
    sd = SoundDirection()
    while True:
        if sd.isdetected():
            print(f"Sound detected at {sd.read()} degrees")
        sleep(0.2)