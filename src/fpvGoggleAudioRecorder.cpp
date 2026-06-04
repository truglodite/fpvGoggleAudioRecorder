/*
    fpvGoggleAudioRecorder.cpp
    Production-oriented FPV goggle audio recorder
    Waveshare RP2040 Zero + ICS43434 + SPI SD

    Features:
    - Crash-resistant segmented recording
    - Dual-core audio pipeline
    - Large ringbuffer
    - Nonblocking LED system
    - SD latency tolerance
    - I2S timeout protection
    - Batch SD writes
    - Safer manifest journaling
    - Watchdog-safe architecture
    - Stable WS2812 handling

    Audio format:
    - RAW PCM
    - signed 16-bit little endian
    - 22050 Hz mono

    Requires:
    - Earle Philhower RP2040 core
*/

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <I2S.h>
#include <Adafruit_NeoPixel.h>
#include "pico/multicore.h"
#include "hardware/watchdog.h"
#include <math.h>

// ======================================================
// CONFIG
// ======================================================

#define SAMPLE_RATE        22050
#define BLOCK_SAMPLES      256
#define QUEUE_BLOCKS       128

#define SEGMENT_MS         120000UL
#define FLUSH_INTERVAL_MS  3000UL

#define SD_CS              5
#define LED_PIN            16

#define I2S_DATA_PIN       12
#define I2S_BCLK_PIN       10

// ======================================================
// LED
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

volatile float globalPeak = 0.0f;
volatile uint32_t lastAudioMs = 0;

// ======================================================
// I2S
// ======================================================

I2S i2s(INPUT);

// ======================================================
// AUDIO BUFFER
// ======================================================

enum BlockState : uint8_t
{
    BLOCK_FREE = 0,
    BLOCK_FILLED = 1
};

struct AudioBlock
{
    int16_t samples[BLOCK_SAMPLES];
    volatile BlockState state;
};

AudioBlock queueBuffer[QUEUE_BLOCKS];

volatile uint16_t writeIndex = 0;
volatile uint16_t readIndex = 0;

// ======================================================
// FILES
// ======================================================

File audioFile;
File manifestFile;

char currentFilename[64];

volatile bool recording = false;

uint32_t sessionId = 0;
uint32_t segmentId = 0;

// ======================================================
// SYSTEM HEALTH
// ======================================================

struct SystemHealth
{
    volatile uint32_t bufferOverruns = 0;
    volatile uint32_t i2sTimeouts = 0;
    volatile uint32_t sdErrors = 0;
    volatile uint32_t writes = 0;
};

SystemHealth sys;

// ======================================================
// LED SYSTEM
// ======================================================

void setLED(uint8_t r, uint8_t g, uint8_t b)
{
    led.setPixelColor(0, led.Color(r, g, b));
    led.show();
}

void updateLED()
{
    static uint32_t lastUpdate = 0;

    if (millis() - lastUpdate < 50)
        return;

    lastUpdate = millis();

    switch (ledMode)
    {
        case LED_BOOT:
        {
            setLED(0, 0, 40);
            break;
        }

        case LED_FATAL:
        {
            static bool blink = false;
            blink = !blink;

            if (blink)
                setLED(80, 0, 0);
            else
                setLED(0, 0, 0);

            break;
        }

        case LED_SD_WARN:
        {
            static bool blink = false;
            blink = !blink;

            if (blink)
                setLED(80, 0, 0);
            else
                setLED(0, 0, 0);

            break;
        }

        case LED_BUFFER_WARN:
        {
            static bool blink = false;
            blink = !blink;

            if (blink)
                setLED(60, 40, 0);
            else
                setLED(0, 0, 0);

            break;
        }

        case LED_RECORDING:
        {
            bool active = (millis() - lastAudioMs) < 250;

            if (!active)
            {
                setLED(0, 2, 0);
            }
            else
            {
                uint8_t level = (uint8_t)min(80.0f, globalPeak / 180.0f);

                if (level < 2)
                    level = 2;

                setLED(0, level, 0);
            }

            break;
        }
    }
}

// ======================================================
// MANIFEST
// ======================================================

void fatalError()
{
    ledMode = LED_FATAL;

    while (1)
    {
        updateLED();
        watchdog_update();
        delay(10);
    }
}

void openManifest()
{
    manifestFile = SD.open("/manifest.log", FILE_WRITE);

    if (!manifestFile)
        fatalError();

    manifestFile.print("SESSION_START,");
    manifestFile.println(millis());
    manifestFile.flush();
}

void logEvent(const char* type, const char* name)
{
    manifestFile.print(type);
    manifestFile.print(",");
    manifestFile.print(name);
    manifestFile.print(",");
    manifestFile.println(millis());

    manifestFile.flush();
}

// ======================================================
// SESSION ID
// ======================================================

uint32_t loadSessionCounter()
{
    uint32_t id = 0;

    File f = SD.open("/session.dat", FILE_READ);

    if (f)
    {
        f.read((uint8_t*)&id, sizeof(id));
        f.close();
    }

    id++;

    f = SD.open("/session.dat", FILE_WRITE);

    if (f)
    {
        f.seek(0);
        f.write((uint8_t*)&id, sizeof(id));
        f.flush();
        f.close();
    }

    return id;
}

// ======================================================
// SEGMENTS
// ======================================================

void openSegment()
{
    segmentId++;

    sprintf(
        currentFilename,
        "/rec_%08lu_%04lu.raw",
        sessionId,
        segmentId
    );

    audioFile = SD.open(currentFilename, FILE_WRITE);

    if (!audioFile)
        fatalError();

    logEvent("OPEN", currentFilename);
}

void closeSegment()
{
    if (!audioFile)
        return;

    audioFile.flush();
    audioFile.close();

    logEvent("CLOSE", currentFilename);
}

// ======================================================
// DSP
// ======================================================

inline int16_t processSample(int32_t s)
{
    static float env = 0.0f;

    float x = (float)(s >> 8);

    // DC blocker
    static float hp = 0;
    static float prev = 0;

    hp = 0.995f * hp + x - prev;
    prev = x;

    x = hp;

    float absx = fabsf(x);

    if (absx > env)
        env = absx;
    else
        env *= 0.9997f;

    float limit = 14000.0f;

    if (env > limit)
        x *= limit / env;

    if (x > 32767) x = 32767;
    if (x < -32768) x = -32768;

    return (int16_t)x;
}

// ======================================================
// AUDIO CORE
// ======================================================

void audioCore()
{
    int32_t left, right;

    while (1)
    {
        if (!recording)
        {
            delay(1);
            continue;
        }

        AudioBlock &block = queueBuffer[writeIndex];

        if (block.state == BLOCK_FILLED)
        {
            sys.bufferOverruns++;
            ledMode = LED_BUFFER_WARN;

            delayMicroseconds(100);
            continue;
        }

        for (int i = 0; i < BLOCK_SAMPLES; i++)
        {
            uint32_t start = micros();

            while (!i2s.available())
            {
                if (micros() - start > 5000)
                {
                    sys.i2sTimeouts++;
                    break;
                }
            }

            i2s.read(&left, &right);

            int16_t sample = processSample(left);

            block.samples[i] = sample;

            float a = fabsf((float)sample);

            if (a > globalPeak)
                globalPeak = a;
            else
                globalPeak *= 0.9995f;
        }

        block.state = BLOCK_FILLED;

        writeIndex++;
        writeIndex %= QUEUE_BLOCKS;

        lastAudioMs = millis();

        if (ledMode != LED_SD_WARN &&
            ledMode != LED_BUFFER_WARN)
        {
            ledMode = LED_RECORDING;
        }
    }
}

// ======================================================
// SD WRITER
// ======================================================

void writeTaskStep()
{
    static uint32_t lastFlush = 0;

    AudioBlock &block = queueBuffer[readIndex];

    if (block.state != BLOCK_FILLED)
        return;

    size_t bytes = audioFile.write(
        (uint8_t*)block.samples,
        sizeof(block.samples)
    );

    if (bytes != sizeof(block.samples))
    {
        sys.sdErrors++;
        ledMode = LED_SD_WARN;
    }

    sys.writes++;

    block.state = BLOCK_FREE;

    readIndex++;
    readIndex %= QUEUE_BLOCKS;

    if (millis() - lastFlush > FLUSH_INTERVAL_MS)
    {
        audioFile.flush();
        lastFlush = millis();
    }
}

// ======================================================
// SELF TEST
// ======================================================

bool runSelfTest()
{
    File f = SD.open("/selftest.tmp", FILE_WRITE);

    if (!f)
        return false;

    uint8_t x = 0x55;

    bool ok = (f.write(&x, 1) == 1);

    f.close();

    SD.remove("/selftest.tmp");

    return ok;
}

// ======================================================
// SETUP
// ======================================================

void setup()
{
    Serial.begin(115200);

    delay(1000);

    // --------------------------------------------------
    // LED INIT
    // --------------------------------------------------

    led.begin();
    led.setBrightness(40);

    led.clear();
    led.show();

    delay(10);

    // boot test
    setLED(0, 0, 50);

    delay(500);

    // --------------------------------------------------
    // WATCHDOG
    // --------------------------------------------------

    watchdog_enable(4000, true);

    // --------------------------------------------------
    // SPI / SD
    // --------------------------------------------------

    SPI.begin();

    if (!SD.begin(SD_CS))
        fatalError();

    // --------------------------------------------------
    // I2S
    // --------------------------------------------------

    i2s.setDATA(I2S_DATA_PIN);
    i2s.setBCLK(I2S_BCLK_PIN);
    i2s.setBitsPerSample(16);

    if (!i2s.begin(SAMPLE_RATE))
        fatalError();

    // --------------------------------------------------
    // BUFFER INIT
    // --------------------------------------------------

    for (int i = 0; i < QUEUE_BLOCKS; i++)
        queueBuffer[i].state = BLOCK_FREE;

    // --------------------------------------------------
    // SELF TEST
    // --------------------------------------------------

    if (!runSelfTest())
        fatalError();

    // --------------------------------------------------
    // SESSION
    // --------------------------------------------------

    sessionId = loadSessionCounter();

    openManifest();

    openSegment();

    recording = true;

    ledMode = LED_RECORDING;

    // --------------------------------------------------
    // START AUDIO CORE
    // --------------------------------------------------

    multicore_launch_core1(audioCore);
}

// ======================================================
// MAIN LOOP
// ======================================================

void loop()
{
    static uint32_t segmentStart = millis();

    watchdog_update();

    writeTaskStep();

    updateLED();

    // segment rollover

    if (millis() - segmentStart > SEGMENT_MS)
    {
        closeSegment();

        openSegment();

        segmentStart = millis();
    }

    delay(1);
}