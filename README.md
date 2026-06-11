# fpvGoggleAudioRecorder
## A reliable audio recording device for FPV goggles

<img src="https://github.com/truglodite/fpvgoggleaudiorecorder/blob/main/enclosure/IMG_2937_1.jpg" width="600">

This code makes use of a Waveshare RP2040 Zero board, an ICS43434 i2s mic, and a 3v3 micro SD card reader to record ambient noises and voices for FPV flying sessions. The Earle Philhower RP2040 Pico library is required to compile. https://github.com/earlephilhower/arduino-pico

### Hardware:
*No pins installed if using the printable enclosure*
- Waveshare RP2040 Zero: https://www.amazon.com/DWEII-RP2040-Zero-Microcontroller-Development-MicroPython/dp/B0C5Q2V49P
- ICS43434 I2S Microphone: https://www.amazon.com/ICS43434-Microphone-Breakout-Module-Filter/dp/B0FMDGRM8F
- Micro SD Card Breakout (3.3V): https://www.amazon.com/WWZMDiB-Module-Adapter-Memory-Shield/dp/B0BV8ZQ81F
- 6mm Momentary NO Tactile Button: https://www.amazon.com/Momentary-Tactile-Through-Breadboard-Friendly/dp/B07WF76VHT

* Note that an INMP441 mic could be used in place of the ICS43434 if needed, but audio quality is not quite as good. Also the printed enclosure only fits the ICS mic.

### Operation
Simply plug in USB power, and the system will start to record. Unplug USB to stop the recording. If you need to start a new file during a recording session, hit the button, a blue LED will flash, and a new file will be started. This can be useful if for example you wait a while for GPS before launching, hit the button so you have an audio file that starts just before launching.

When powering on, you should first see a blue LED to indicate boot status followed by a pulsating green LED to indicate normal recording, and with an occasional red flash during louder noises to indicate the clipping limiter is active. If you see just a repeating flashing red led, the SD card is failing. If you see an orange flashing LED, the audio buffer is falling behind.

For convenience I created a windows executable to quickly convert raw files recorded with the fpvGoggleAudioRecorder into easy to use wav files (raw2wav.exe, in raw2wav/dist/). Click the exe, select the input folder (your SD card) and an output folder. The "rec_XXXXXXXX_YYYY.raw" files will be converted to "rec_XXXXXXXX_YYYY.wav" files and copied to your PC, ready for use with your favorite video editor.

<img src="https://github.com/truglodite/fpvgoggleaudiorecorder/blob/main/raw2wav/raw2wav.png" width="600">

### Recording Format:
Similar to how a dashcam/bodycam works, this code records audio to raw PCM files with routines that prevent data corruption when power is suddenly lost while recording. When power is cutoff, only the last seconds of the recording session will be lost. The files are named "rec_X-Y.raw", where X is the recording session, and Y is the audio segment. Both X and Y increment to allow easy reconstruction of wav files. The "manifest.txt" file keeps a log of segments that have been saved, as well as segments that were lost due to power cutoff. The newest segments will be at the top of the manifest file.

The code makes use of an RMS audio compressor with smooth clipping that has been somewhat optimized for the hardware and intended application. Voices and noises farther away will have a similar volume to the voice of the person wearing the mic. Due to "aggressive AGC parameters", there will be some noise underlying the audio, but it is minimal. The audio performance with the ICS43434 using approach results much higher quality audio compared to the usual MAX9815+ADC setup.

To create wav files from the raw files, you can use Audacity to "Import/Raw Data", and choose "little endian" and "Sample Rate: 44000". Alternatively, you can use the included executable converter.

### Compiling/Flashing:
The code comes ready to compile with VSCode using the PlatformIO extension. To flash your RP2040, hold the boot button then push the reset button to put the board into DFU mode. Hit the right arrow button at the bottom, and PlatformIO should load a UF2 file on the board. This code can also be compiled with Arduino IDE by adding the earlephilhower core (see the github link at the top of the readme).

### Wiring:
Connect the hardware as shown in the table below. The button is optional for manual recording variants, and is not required for autorecording.

Device  |   Pin |   RP2040 Pin
----|-----|----
MIC |   SEL |   GND
MIC |   LRCL |   11
MIC |   DOUT |   12
MIC |   BCLK |   10
MIC |   GND |   GND
MIC |   3V |   3v3
SD |   GND |   GND
SD |   MISO |   4
SD |   CLK |   2
SD |   MOSI |   3
SD |   CS |   5
SD |    3v3 |   3v3
BUTT |   A/B |   6/GND

<img src="https://github.com/truglodite/fpvgoggleaudiorecorder/blob/main/enclosure/IMG_2936_1.jpg" width="600">

### Printable Enclosure:
Files for a printable enclosure are provided in this repo. One of each part should be printed. Print the "agcRecorderTopWindscreen.stl" if you want to use a 10mm foam or furry cover for the mic. ABS or PETG is recommended for the top, bottom, and shim. Clear PETG filament should be used for the lens. Some glue is needed for a durable assembly; I used T-7000 glue on all of the joints described below.

To assemble the enclosure, first test fit your button, boards, and mic in the enclosure top/bottom. The mic is oriented with pin holes toward the top, with the mic hole facing out the side with the hole in it. The RP2040 is inserted with buttons facing the top, USB out the side. The button is rotated with pin sides facing the mic/usb sides of the enclosure. The SD card board is placed with the metal card insert part facing toward the top. First insert the lens, button, and mic in the top half, then insert the RP2040 board. Insert the SD board in the bottom half. Place the board shim over the RP2040 processor, and press the bottom half onto the top half. There are tabs for a click fit between the top/bottom halves. When assembled, verify the button protrudes out the top enough for easy operation, the SD card is easy to insert/remove, USB cable is easy to get to, and the case halves close completely. There should be an even 1mm gap around the edge where the top/bottom halves fit together. Also make sure you can fit a paper clip or similar rod through the Boot/Reset button access holes located near the lens.

The enclosure is very compact; 30awg silicone wire or smaller is recommended. Make all wires long enough to reach when assembled, but not so long that assembly can pinch a wire. Leave enough length on the SD card wires so the enclosure halves can easily be assembled/disassembled. Solder wires for the button and add heatshrink; break off the unused pins from the other side of the button. Solder wires to the chip side of the microphone. Solder wires to the back side (opposite of boot/reset buttons) on the RP2040. When wires are all soldered, glue the button into place taking care not to allow glue to squirt where it may interfere with operation. Glue the lens into the top half of the case. Add glue to the rails where the RP2040 and SD card boards will rest, and insert the components into the case halves. Snap case halves together taking care not to pinch any wires. Add the windscreen cover if desired; some glue around the bottom of the windstopper basket where it touches the box will offer a more reliable hold.
