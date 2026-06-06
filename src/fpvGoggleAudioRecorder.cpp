/*
    fpvGoggleAudioRecorder.cpp
    Production-oriented FPV goggle audio recorder

    Hardware:
    - Waveshare RP2040 Zero
    - ICS43434 I2S microphone
    - SPI microSD

    Features:
    - Dual-core audio pipeline
    - Large ring buffer
    - Crash-resistant segmented recording
    - SD write retries
    - Core1 heartbeat monitoring
    - I2S timeout recovery
    - Queue synchronization barriers
    - Disk full detection
    - Watchdog recovery
    - Non-blocking LED updates

    Audio:
    - RAW PCM
    - Signed 16-bit little endian
    - 22050 Hz mono

    Requires:
    - Arduino-Pico (Earle Philhower)
*/

#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <I2S.h>
#include <Adafruit_NeoPixel.h>

#include "pico/multicore.h"
#include "hardware/watchdog.h"
#include "hardware/sync.h"

#include <math.h>

// ======================================================
// CONFIG
// ======================================================

#define SAMPLE_RATE            22050

#define BLOCK_SAMPLES          256
#define QUEUE_BLOCKS           128

#define SEGMENT_MS             120000UL
#define FLUSH_INTERVAL_MS      3000UL

#define SD_CS                  5
#define LED_PIN                16

#define I2S_DATA_PIN           12
#define I2S_BCLK_PIN           10

#define WATCHDOG_TIMEOUT_MS    4000
#define CORE1_TIMEOUT_MS       2000

#define MEMORY_BARRIER()       __dmb()

// ======================================================
// LED
// ======================================================

Adafruit_NeoPixel led(
    1,
    LED_PIN,
    NEO_GRB + NEO_KHZ800
);

enum LedMode
{
    LED_BOOT,
    LED_RECORDING,
    LED_SD_WARN,
    LED_BUFFER_WARN,
    LED_FATAL
};

volatile LedMode ledMode = LED_BOOT;

// ======================================================
// SHARED STATE
// ======================================================

volatile uint16_t globalPeak = 0;
volatile uint32_t lastAudioMs = 0;

volatile uint32_t core1Heartbeat = 0;

volatile bool fatalState = false;
volatile bool sdWarning = false;
volatile bool bufferWarning = false;
volatile bool diskFull = false;

volatile bool recording = false;
volatile bool rolloverPending = false;

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
volatile uint16_t readIndex  = 0;

// ======================================================
// FILES
// ======================================================

File audioFile;
File manifestFile;

char currentFilename[64];

uint32_t sessionId = 0;
uint32_t segmentId = 0;

// ======================================================
// SYSTEM HEALTH
// ======================================================

struct SystemHealth
{
    volatile uint32_t bufferOverruns = 0;
    volatile uint32_t i2sTimeouts    = 0;
    volatile uint32_t sdErrors       = 0;
    volatile uint32_t writes         = 0;
};

SystemHealth sys;

// ======================================================
// LED HELPERS
// ======================================================

void setLED(
    uint8_t r,
    uint8_t g,
    uint8_t b
)
{
    led.setPixelColor(
        0,
        led.Color(r, g, b)
    );

    led.show();
}

void updateLedState()
{
    if (fatalState)
    {
        ledMode = LED_FATAL;
        return;
    }

    if (diskFull)
    {
        ledMode = LED_FATAL;
        return;
    }

    if (sdWarning)
    {
        ledMode = LED_SD_WARN;
        return;
    }

    if (bufferWarning)
    {
        ledMode = LED_BUFFER_WARN;
        return;
    }

    ledMode = LED_RECORDING;
}

void updateLED()
{
    static uint32_t lastUpdate = 0;

    if ((millis() - lastUpdate) < 50)
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
                setLED(100, 0, 0);
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
                setLED(80, 40, 0);
            else
                setLED(0, 0, 0);

            break;
        }

        case LED_RECORDING:
        {
            bool active =
                (millis() - lastAudioMs) < 250;

            if (!active)
            {
                setLED(0, 2, 0);
            }
            else
            {
                uint8_t level =
                    constrain(
                        map(
                            globalPeak,
                            0,
                            16000,
                            2,
                            80
                        ),
                        2,
                        80
                    );

                setLED(0, level, 0);
            }

            break;
        }
    }
}

// ======================================================
// FATAL HANDLER
// ======================================================

void fatalError()
{
    fatalState = true;

    while (1)
    {
        updateLedState();
        updateLED();

        // intentionally do NOT feed watchdog

        delay(10);
    }
}
// ======================================================
// MANIFEST
// ======================================================

void openManifest()
{
    manifestFile = SD.open(
        "/manifest.log",
        FILE_WRITE
    );

    if (!manifestFile)
        fatalError();

    manifestFile.print("SESSION_START,");
    manifestFile.println(millis());

    manifestFile.flush();
}

void logEvent(
    const char *type,
    const char *name
)
{
    if (!manifestFile)
        return;

    manifestFile.print(type);
    manifestFile.print(",");
    manifestFile.print(name);
    manifestFile.print(",");
    manifestFile.println(millis());

    manifestFile.flush();
}

// ======================================================
// SESSION COUNTER
// ======================================================

uint32_t loadSessionCounter()
{
    uint32_t id = 0;

    File f = SD.open(
        "/session.dat",
        FILE_READ
    );

    if (f)
    {
        if (f.available() >= sizeof(id))
        {
            f.read(
                (uint8_t *)&id,
                sizeof(id)
            );
        }

        f.close();
    }

    id++;

    f = SD.open(
        "/session.dat",
        FILE_WRITE
    );

    if (f)
    {
        f.seek(0);

        f.write(
            (uint8_t *)&id,
            sizeof(id)
        );

        f.flush();
        f.close();
    }

    return id;
}

// ======================================================
// SEGMENT MANAGEMENT
// ======================================================

void openSegment()
{
    segmentId++;

    snprintf(
        currentFilename,
        sizeof(currentFilename),
        "/rec_%08lu_%04lu.raw",
        (unsigned long)sessionId,
        (unsigned long)segmentId
    );

    audioFile = SD.open(
        currentFilename,
        FILE_WRITE
    );

    if (!audioFile)
        fatalError();

    logEvent(
        "OPEN",
        currentFilename
    );
}

void closeSegment()
{
    if (!audioFile)
        return;

    audioFile.flush();
    audioFile.close();

    logEvent(
        "CLOSE",
        currentFilename
    );
}

// ======================================================
// QUEUE HELPERS
// ======================================================

bool queueEmpty()
{
    for (int i = 0; i < QUEUE_BLOCKS; i++)
    {
        if (
            queueBuffer[i].state ==
            BLOCK_FILLED
        )
        {
            return false;
        }
    }

    return true;
}

uint32_t queueUsed()
{
    uint32_t count = 0;

    for (int i = 0; i < QUEUE_BLOCKS; i++)
    {
        if (
            queueBuffer[i].state ==
            BLOCK_FILLED
        )
        {
            count++;
        }
    }

    return count;
}

// ======================================================
// DSP STATE
// ======================================================

struct DSPState
{
    float hp;
    float prev;
    float env;
};

DSPState dsp =
{
    0.0f,
    0.0f,
    0.0f
};

// ======================================================
// DSP
// ======================================================

inline int16_t processSample(
    int32_t sample
)
{
    float x =
        (float)(sample >> 8);

    // ----------------------------------
    // DC blocker
    // ----------------------------------

    dsp.hp =
        0.995f * dsp.hp +
        x -
        dsp.prev;

    dsp.prev = x;

    x = dsp.hp;

    // ----------------------------------
    // Envelope tracker
    // ----------------------------------

    float absx = fabsf(x);

    if (absx > dsp.env)
    {
        dsp.env = absx;
    }
    else
    {
        dsp.env *= 0.9997f;
    }

    // ----------------------------------
    // Soft limiter
    // ----------------------------------

    const float limit = 14000.0f;

    if (dsp.env > limit)
    {
        x *=
            (
                limit /
                dsp.env
            );
    }

    // ----------------------------------
    // Clamp
    // ----------------------------------

    if (x > 32767.0f)
        x = 32767.0f;

    if (x < -32768.0f)
        x = -32768.0f;

    return (int16_t)x;
}

// ======================================================
// PEAK TRACKER
// ======================================================

inline void updatePeak(
    int16_t sample
)
{
    uint16_t a =
        abs(sample);

    uint16_t peak =
        globalPeak;

    if (a > peak)
    {
        globalPeak = a;
    }
    else if (peak > 0)
    {
        globalPeak = peak - 1;
    }
}

// ======================================================
// SELF TEST
// ======================================================

bool runSelfTest()
{
    File f =
        SD.open(
            "/selftest.tmp",
            FILE_WRITE
        );

    if (!f)
        return false;

    uint8_t x = 0x55;

    bool ok =
        (
            f.write(&x, 1)
            ==
            1
        );

    f.close();

    SD.remove(
        "/selftest.tmp"
    );

    return ok;
}
// ======================================================
// AUDIO CORE (CORE 1)
// ======================================================

void audioCore()
{
    int32_t left = 0;
    int32_t right = 0;

    while (1)
    {
        // ---------------------------------
        // Wait for recording enable
        // ---------------------------------

        if (!recording)
        {
            delay(1);
            continue;
        }

        // ---------------------------------
        // Heartbeat
        // ---------------------------------

        core1Heartbeat = millis();

        // ---------------------------------
        // Acquire current block
        // ---------------------------------

        AudioBlock &block =
            queueBuffer[writeIndex];

        // ---------------------------------
        // Queue full?
        // ---------------------------------

        if (
            block.state ==
            BLOCK_FILLED
        )
        {
            sys.bufferOverruns++;

            bufferWarning = true;

            delayMicroseconds(100);

            continue;
        }

        // ---------------------------------
        // Fill block
        // ---------------------------------

        for (
            int i = 0;
            i < BLOCK_SAMPLES;
            i++
        )
        {
            uint32_t startUs =
                micros();

            bool gotSample =
                false;

            // -----------------------------
            // Wait for I2S
            // -----------------------------

            while (!i2s.available())
            {
                if (
                    micros() - startUs
                    >
                    5000
                )
                {
                    sys.i2sTimeouts++;

                    break;
                }
            }

            // -----------------------------
            // Read sample if available
            // -----------------------------

            if (i2s.available())
            {
                i2s.read(
                    &left,
                    &right
                );

                gotSample = true;
            }

            // -----------------------------
            // Timeout fallback
            // -----------------------------

            if (!gotSample)
            {
                left = 0;
                right = 0;
            }

            // -----------------------------
            // Process sample
            // -----------------------------

            int16_t pcm =
                processSample(left);

            block.samples[i] =
                pcm;

            updatePeak(pcm);
        }

        // ---------------------------------
        // Publish block safely
        // ---------------------------------

        MEMORY_BARRIER();

        block.state =
            BLOCK_FILLED;

        MEMORY_BARRIER();

        writeIndex++;

        if (
            writeIndex >=
            QUEUE_BLOCKS
        )
        {
            writeIndex = 0;
        }

        lastAudioMs =
            millis();

        // ---------------------------------
        // Clear warning if queue healthy
        // ---------------------------------

        uint32_t used =
            queueUsed();

        if (
            used <
            (QUEUE_BLOCKS / 2)
        )
        {
            bufferWarning = false;
        }
    }
}
// ======================================================
// SD WRITE HELPERS
// ======================================================

bool writeAudioBlock(
    AudioBlock &block
)
{
    const size_t expected =
        sizeof(block.samples);

    size_t bytes = 0;

    for (
        int retry = 0;
        retry < 3;
        retry++
    )
    {
        bytes =
            audioFile.write(
                (uint8_t *)block.samples,
                expected
            );

        if (bytes == expected)
        {
            return true;
        }

        delay(2);
    }

    return false;
}

// ======================================================
// WRITER TASK
// ======================================================

void writeTaskStep()
{
    static uint32_t lastFlush = 0;

    // ---------------------------------
    // Current queue block
    // ---------------------------------

    AudioBlock &block =
        queueBuffer[readIndex];

    // ---------------------------------
    // No work
    // ---------------------------------

    if (
        block.state !=
        BLOCK_FILLED
    )
    {
        // -----------------------------
        // Handle rollover only after
        // queue fully drained
        // -----------------------------

        if (
            rolloverPending &&
            queueEmpty()
        )
        {
            if (audioFile)
            {
                audioFile.flush();
            }

            closeSegment();

            openSegment();

            rolloverPending = false;
        }

        return;
    }

    // ---------------------------------
    // SD write
    // ---------------------------------

    bool ok =
        writeAudioBlock(
            block
        );

    if (!ok)
    {
        sys.sdErrors++;

        sdWarning = true;

        // crude disk-full indication
        // repeated failures usually mean:
        // - card removed
        // - card full
        // - filesystem issue

        if (
            sys.sdErrors > 10
        )
        {
            diskFull = true;
        }
    }
    else
    {
        sys.writes++;

        if (
            sys.sdErrors == 0
        )
        {
            sdWarning = false;
        }
    }

    // ---------------------------------
    // Release queue block
    // ---------------------------------

    MEMORY_BARRIER();

    block.state =
        BLOCK_FREE;

    MEMORY_BARRIER();

    readIndex++;

    if (
        readIndex >=
        QUEUE_BLOCKS
    )
    {
        readIndex = 0;
    }

    // ---------------------------------
    // Periodic flush
    // ---------------------------------

    if (
        millis() -
        lastFlush
        >
        FLUSH_INTERVAL_MS
    )
    {
        if (audioFile)
        {
            audioFile.flush();
        }

        if (manifestFile)
        {
            manifestFile.flush();
        }

        lastFlush =
            millis();
    }

    // ---------------------------------
    // Segment rollover
    // ---------------------------------

    if (
        rolloverPending &&
        queueEmpty()
    )
    {
        if (audioFile)
        {
            audioFile.flush();
        }

        closeSegment();

        openSegment();

        rolloverPending = false;
    }
}

// ======================================================
// STATUS LOGGER
// ======================================================

void printStats()
{
    static uint32_t lastPrint = 0;

    if (
        millis() -
        lastPrint
        <
        5000
    )
    {
        return;
    }

    lastPrint = millis();

    Serial.print("writes=");
    Serial.print(sys.writes);

    Serial.print(" overruns=");
    Serial.print(sys.bufferOverruns);

    Serial.print(" i2s=");
    Serial.print(sys.i2sTimeouts);

    Serial.print(" sd=");
    Serial.print(sys.sdErrors);

    Serial.print(" queued=");
    Serial.println(queueUsed());
}
// ======================================================
// SETUP
// ======================================================

void setup()
{
    Serial.begin(115200);
    delay(1000);

    // -----------------------------
    // LED INIT
    // -----------------------------

    led.begin();
    led.setBrightness(40);
    led.clear();
    led.show();

    setLED(0, 0, 50);
    delay(300);

    // -----------------------------
    // WATCHDOG
    // -----------------------------

    watchdog_enable(
        WATCHDOG_TIMEOUT_MS,
        true
    );

    // -----------------------------
    // SPI / SD INIT
    // -----------------------------

    SPI.begin();

    if (!SD.begin(SD_CS))
    {
        fatalError();
    }

    if (!runSelfTest())
    {
        fatalError();
    }

    // -----------------------------
    // I2S INIT
    // -----------------------------

    i2s.setDATA(I2S_DATA_PIN);
    i2s.setBCLK(I2S_BCLK_PIN);
    i2s.setBitsPerSample(16);

    if (!i2s.begin(SAMPLE_RATE))
    {
        fatalError();
    }

    // -----------------------------
    // INIT BUFFER
    // -----------------------------

    for (int i = 0; i < QUEUE_BLOCKS; i++)
    {
        queueBuffer[i].state = BLOCK_FREE;
    }

    writeIndex = 0;
    readIndex = 0;

    // -----------------------------
    // SESSION + FILES
    // -----------------------------

    sessionId = loadSessionCounter();

    openManifest();

    openSegment();

    recording = true;

    // -----------------------------
    // CORE 1 START
    // -----------------------------

    multicore_launch_core1(audioCore);

    // mark alive
    core1Heartbeat = millis();
}

// ======================================================
// WATCHDOG / SAFETY CHECKS
// ======================================================

void checkCore1Health()
{
    if (
        millis() - core1Heartbeat
        > CORE1_TIMEOUT_MS
    )
    {
        fatalState = true;

        Serial.println("CORE1 DEAD");

        closeSegment();

        watchdog_reboot(0, 0, 0);
    }
}

void checkDiskState()
{
    if (diskFull)
    {
        recording = false;

        closeSegment();

        logEvent("DISK_FULL", currentFilename);

        fatalError();
    }
}

// ======================================================
// MAIN LOOP
// ======================================================

void loop()
{
    // -----------------------------
    // watchdog feed
    // -----------------------------

    watchdog_update();

    // -----------------------------
    // writer task
    // -----------------------------

    writeTaskStep();

    // -----------------------------
    // LED state resolve
    // -----------------------------

    updateLedState();
    updateLED();

    // -----------------------------
    // health checks
    // -----------------------------

    checkCore1Health();
    checkDiskState();

    // -----------------------------
    // debug stats
    // -----------------------------

    printStats();

    // -----------------------------
    // yield
    // -----------------------------

    delay(1);
}

// ======================================================
// END OF FILE
// ======================================================