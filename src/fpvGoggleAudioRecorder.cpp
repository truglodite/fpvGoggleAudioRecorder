/*
fpvGoggleAudioRecorder.cpp
This code uses a Waveshare RP2040 Zero, ICS43434 mic, and 3v3 SDcard to reliably record audio
for FPV goggles (such as DJI). Simply plug it in to the Goggle USB for power, and it will start recording.
Unplug or power off to stop recording. Files are in *.raw format, little endian, 22050hz.
Filenames indicate sessions, and a file manifest is included to reconstruct recording sessions.
*/

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <I2S.h>
#include <Adafruit_NeoPixel.h>
#include "pico/multicore.h"

// ======================================================
// CONFIG
// ======================================================

#define SAMPLE_RATE     22050
#define BLOCK_SAMPLES   256
#define QUEUE_BLOCKS    32

#define SD_CS 5
#define LED_PIN 16

// ======================================================
// LED SYSTEM
// ======================================================

Adafruit_NeoPixel led(1, LED_PIN, NEO_GRB + NEO_KHZ800);

enum LedMode
{
    LED_BOOT,
    LED_RECORDING,
    LED_SD_WARN,
    LED_BUFFER_WARN,
    LED_FATAL
};

volatile LedMode ledMode = LED_BOOT;

volatile uint32_t lastAudioBlockMs = 0;
volatile float globalPeak = 0.0f;

// ======================================================
// I2S
// ======================================================

I2S i2s(INPUT);

// ======================================================
// AUDIO BUFFER
// ======================================================

enum BlockState : uint8_t
{
    FREE = 0,
    FILLED = 1
};

struct AudioBlock
{
    int16_t samples[BLOCK_SAMPLES];
    volatile BlockState state;
};

AudioBlock buffer[QUEUE_BLOCKS];

volatile uint8_t wIndex = 0;
volatile uint8_t rIndex = 0;

// ======================================================
// FILE STATE
// ======================================================

File audioFile;
File manifestFile;

volatile bool recording = false;

uint32_t sessionId = 0;
uint32_t segmentId = 0;

char filename[64];

// ======================================================
// SYSTEM HEALTH
// ======================================================

struct SystemHealth
{
    uint32_t sdWriteErrors = 0;
    uint32_t bufferOverruns = 0;
    uint32_t totalWrites = 0;

    uint32_t sdLatencySum = 0;
    uint32_t sdLatencySamples = 0;

    bool sdOK = false;
};

SystemHealth sys;

// ======================================================
// LED UPDATE (SYNCED + PEAK DRIVEN)
// ======================================================

void updateLED()
{
    static uint32_t last = 0;
    if (millis() - last < 50)
        return;
    last = millis();

    if (ledMode == LED_FATAL)
    {
        led.setPixelColor(0, led.Color(80, 0, 0));
        led.show();
        return;
    }

    if (ledMode == LED_BOOT)
    {
        led.setPixelColor(0, led.Color(0, 0, 80));
        led.show();
        return;
    }

    if (ledMode == LED_BUFFER_WARN)
    {
        led.setPixelColor(0, led.Color(80, 80, 0));
        led.show();
        return;
    }

    if (ledMode == LED_SD_WARN)
    {
        led.setPixelColor(0, led.Color(80, 0, 0));
        led.show();
        return;
    }

    if (ledMode == LED_RECORDING)
    {
        bool audioActive = (millis() - lastAudioBlockMs) < 200;

        if (!audioActive)
        {
            led.setPixelColor(0, led.Color(0, 1, 0));
        }
        else
        {
            static bool flip = false;
            flip = !flip;

            uint8_t base = (uint8_t)min(120.0f, globalPeak / 200.0f);
            uint8_t g = flip ? base : base / 4;

            led.setPixelColor(0, led.Color(0, g, 0));
        }

        led.show();
    }
}

// ======================================================
// MANIFEST SYSTEM (SELF-HEALING JOURNAL)
// ======================================================

void openManifest()
{
    manifestFile = SD.open("/manifest.log", FILE_WRITE);

    if (!manifestFile)
    {
        ledMode = LED_FATAL;
        while (1) updateLED();
    }

    manifestFile.print("S,");
    manifestFile.println(millis());
    manifestFile.flush();
}

void logSegmentOpen(const char* name)
{
    manifestFile.print("F,");
    manifestFile.print(name);
    manifestFile.print(",");
    manifestFile.println("OPEN");
    manifestFile.flush();
}

void logSegmentClose(const char* name)
{
    manifestFile.print("F,");
    manifestFile.print(name);
    manifestFile.print(",");
    manifestFile.println("CLOSED");
    manifestFile.flush();
}

// ======================================================
// SEGMENT MANAGEMENT
// ======================================================

void openSegment()
{
    segmentId++;

    sprintf(filename,
        "/rec_%lu_%lu.raw",
        sessionId,
        segmentId
    );

    audioFile = SD.open(filename, FILE_WRITE);

    if (!audioFile)
    {
        ledMode = LED_FATAL;
        while (1) updateLED();
    }

    logSegmentOpen(filename);

    for (int i = 0; i < QUEUE_BLOCKS; i++)
        buffer[i].state = FREE;
}

void closeSegment()
{
    if (!audioFile)
        return;

    audioFile.flush();
    audioFile.close();

    logSegmentClose(filename);
}

// ======================================================
// DSP (FIXED LIMITER - NO CLIPPING)
// ======================================================

inline int16_t processSample(int32_t s)
{
    static float peakEnv = 0.0f;

    float x = (float)(s >> 8);

    float absx = fabs(x);

    if (absx > peakEnv)
        peakEnv = absx;
    else
        peakEnv *= 0.9995f;

    float limit = 12000.0f;

    float gain = 1.0f;
    if (peakEnv > limit)
        gain = limit / peakEnv;

    x *= gain;

    if (x > 32767) x = 32767;
    if (x < -32768) x = -32768;

    return (int16_t)x;
}

// ======================================================
// AUDIO CORE (PRODUCER)
// ======================================================

void audioCore()
{
    int32_t l, r;

    while (true)
    {
        if (!recording)
        {
            delay(1);
            continue;
        }

        AudioBlock &b = buffer[wIndex];

        if (b.state == FILLED)
        {
            sys.bufferOverruns++;
            delayMicroseconds(50);
            continue;
        }

        for (int i = 0; i < BLOCK_SAMPLES; i++)
        {
            while (!i2s.available()) {}
            i2s.read(&l, &r);

            b.samples[i] = processSample(l);

            float absx = fabs((float)b.samples[i]);

            if (absx > globalPeak)
                globalPeak = absx;
            else
                globalPeak *= 0.9995f;
        }

        b.state = FILLED;
        wIndex = (wIndex + 1) % QUEUE_BLOCKS;

        lastAudioBlockMs = millis();
    }
}

// ======================================================
// SD WRITER (CONSUMER)
// ======================================================

void writeTask()
{
    static uint32_t flushCounter = 0;

    while (recording)
    {
        AudioBlock &b = buffer[rIndex];

        if (b.state == FILLED)
        {
            uint32_t t0 = micros();

            size_t written = audioFile.write(
                (uint8_t*)b.samples,
                BLOCK_SAMPLES * 2
            );

            uint32_t dt = micros() - t0;

            sys.sdLatencySum += dt;
            sys.sdLatencySamples++;
            sys.totalWrites++;

            if (written != BLOCK_SAMPLES * 2)
                sys.sdWriteErrors++;

            b.state = FREE;

            rIndex = (rIndex + 1) % QUEUE_BLOCKS;

            if (++flushCounter >= 64)
            {
                audioFile.flush();
                flushCounter = 0;
            }
        }
        else
        {
            delayMicroseconds(50);
        }
    }
}

// ======================================================
// SELF TEST
// ======================================================

bool runSelfTest()
{
    File t = SD.open("/__test.tmp", FILE_WRITE);

    if (!t)
        return false;

    uint8_t b = 0xAA;

    if (t.write(&b, 1) != 1)
        return false;

    t.close();
    SD.remove("/__test.tmp");

    sys.sdOK = true;
    return true;
}

// ======================================================
// SETUP
// ======================================================

void setup()
{
    Serial.begin(115200);
    delay(1000);

    led.begin();
    led.setBrightness(40);

    SPI.begin();

    if (!SD.begin(SD_CS))
    {
        ledMode = LED_FATAL;
        while (1) updateLED();
    }

    i2s.setDATA(12);
    i2s.setBCLK(10);
    i2s.setBitsPerSample(16);

    if (!i2s.begin(SAMPLE_RATE))
    {
        ledMode = LED_FATAL;
        while (1) updateLED();
    }

    if (!runSelfTest())
    {
        ledMode = LED_FATAL;
        while (1) updateLED();
    }

    sessionId = millis();

    openManifest();
    openSegment();

    recording = true;

    ledMode = LED_RECORDING;

    multicore_launch_core1(audioCore);
}

// ======================================================
// LOOP
// ======================================================

void loop()
{
    writeTask();
    updateLED();

    static uint32_t segStart = millis();

    if (millis() - segStart > 120000)
    {
        closeSegment();
        openSegment();
        segStart = millis();
    }
}