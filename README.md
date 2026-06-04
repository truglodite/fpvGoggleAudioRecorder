# fpvGoggleAudioRecorder
## A reliable audio recording device for FPV goggles
This code makes use of a Waveshare RP2040 Zero board, an ICS43434 i2s mic, and a 3v3 micro SD card reader to record ambient noises and voices for FPV flying sessions.

### Hardware:
*No pins installed if using the printable enclosure*
- Waveshare RP2040 Zero: https://www.amazon.com/DWEII-RP2040-Zero-Microcontroller-Development-MicroPython/dp/B0C5Q2V49P
- ICS43434 I2S Microphone: https://www.amazon.com/ICS43434-Microphone-Breakout-Module-Filter/dp/B0FMDGRM8F
- Micro SD Card Breakout (3.3V): https://www.amazon.com/WWZMDiB-Module-Adapter-Memory-Shield/dp/B0BV8ZQ81F
- 6mm Momentary NO Tactile Button (optional): https://www.amazon.com/Momentary-Tactile-Through-Breadboard-Friendly/dp/B07WF76VHT

### Recording Format:
Similar to how a dashcam/bodycam works, this code records audio to *.raw files in a way that prevents data corruption when power is suddenly lost during recording. When power is cutoff, only the last seconds of the recording session will be lost. The files are named "rec_X-Y.raw", where X is the recording session, and Y is the audio segment. Both X and Y increment to allow easy reconstruction of wav files. The "manifest.txt" file keeps a log of segments that have been saved, as well as segments that were lost due to power cutoff. The newest segments will be at the top of the manifest file.

The code makes use of an RMS audio compressor with smooth clipping that has been somewhat optimized for the hardware and intended application. Voices and noises farther away will have a similar volume to the voice of the person wearing the mic. Due to "aggressive AGC parameters", there will be some noise underlying the audio, but it is minimal. The audio performance with the ICS43434 using approach results much higher quality audio compared to the usual MAX9815+ADC setup.

To create wav files from raw files, you can use Audacity to "Import/Raw Data", and choose "little endian", "Sample Rate: 22050".

### Wiring:
Connect the hardware as shown in the table below. The button is optional for manual recording variants, and is not required for autorecording.

Device  |   Pin |   RP2040 Pin
-------------------------
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
BUTT |   to GND |   6

### Printable Enclosure:
Files for a printable enclosure are provided in this repo. One of each part should be printed. ABS or PETG is recommended for the top, bottom, and shim. Clear PETG filament should be used for the lens.

To assemble the enclosure, first test fit your button, boards, and mic in the enclosure top/bottom. The mic is oriented with pin holes toward the top, with the mic hole facing out the side with the hole in it. The RP2040 is inserted with buttons facing the top, USB out the side. The button is rotated with pin sides facing the mic/usb sides of the enclosure. The SD card board is placed with the metal card insert part facing toward the top. First insert the lens, button, and mic in the top half, then insert the RP2040 board. Insert the SD board in the bottom half. Place the board shim over the RP2040 processor, and press the bottom half onto the top half. There are tabs for a click fit between the top/bottom halves. When assembled, verify the button protrudes out the top enough for easy operation, the SD card is easy to insert/remove, USB cable is easy to get to, and the case halves close completely. There should be an even 1mm gap around the edge where the top/bottom halves fit together. Also make sure you can fit a paper clip or similar rod through the Boot/Reset button access holes located near the lens.

The enclosure is very compact; 30awg silicone wire or smaller is recommended. Make all wires long enough to reach when assembled, but not so long that assembly can pinch a wire. Leave enough length on the SD card wires so the enclosure halves can easily be assembled/disassembled. Solder wires for the button and add heatshrink; break off the unused pins from the other side of the button. Solder wires to the chip side of the microphone. Solder wires to the back side (opposite of boot/reset buttons) on the RP2040. When wires are all soldered, glue the button into place taking care not to allow glue to squirt where it may interfere with operation. Glue the lens into the top half of the case. Insert the components and shim into the case halves. Snap case halves together taking care not to pinch any wires.
