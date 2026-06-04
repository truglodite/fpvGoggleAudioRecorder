* fpvGoggleAudioRecorder
** A reliable audio recording device for FPV goggles
This code makes use of a Waveshare RP2040 Zero board, an ICS43434 i2s mic, and a 3v3 micro SD card reader to record ambient noises and voices for FPV flying sessions.

*** Recording Format:
Similar to how a dashcam/bodycam works, this code records audio to *.raw files in a way that prevents data corruption when power is suddenly lost during recording. When power is cutoff, only the last seconds of the recording session will be lost. The files are named "rec_X-Y.raw", where X is the recording session, and Y is the audio segment. Both X and Y increment to allow easy reconstruction of wav files. The "manifest.txt" file keeps a log of segments that have been saved, as well as segments that were lost due to power cutoff. The newest segments will be at the top of the manifest file.

The code makes use of an RMS audio compressor with smooth clipping that has been somewhat optimized for the hardware. Voices and noises farther away will have a similar volume to the voice of the person wearing the mic. Due to "aggressive AGC parameters", there will be some noise underlying the audio, but it is minimal. The audio performance with this approach, using the ICS43434 mic, is far cleaner sounding than the usual MAX9815 setup.

To create wav files from raw files, you can use Audacity to "Import/Raw Data", and choose "little endian", "Sample Rate: 22050".