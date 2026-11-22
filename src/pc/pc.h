// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Syncr0ndi
/* The parts of a 1984 IBM PC (5150/XT) that Alley Cat uses, around the recompiled 8086 code:
 * 1 MB of memory with CAT.EXE loaded as DOS would, a small C BIOS (INT 10h/11h/1Ah), the
 * 8253 timer (channel 0 read-back, channel 2 -> PC speaker), the keyboard on IRQ 1 with a
 * minimal 8259, and CGA video timing (port 3DAh) plus the mode/colour registers.
 *
 * Time is counted in CPU cycles of a 4.77 MHz 8088. The host gets a callback once per CGA
 * frame (59.92 Hz) to present the picture, collect input and pace against real time. */
#pragma once
#include "v30.h"
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#define PC_CPU_HZ      4772727.0       /* 14.31818 MHz / 3 */
#define PC_PIT_DIV     4               /* PIT clock = CPU clock / 4 = 1.193182 MHz */
#define PC_LINE_CYC    304             /* 912 CGA hdots / 3 */
#define PC_FRAME_LINES 262
#define PC_FRAME_CYC   (PC_LINE_CYC * PC_FRAME_LINES)

#define PC_PSP_SEG     0x1000          /* must match tools/catmap.py */
#define PC_LOAD_SEG    (PC_PSP_SEG + 0x10)

#define PC_AUDIO_RATE  44100
#define PC_AUDIO_MAX   8192

typedef struct PC PC;
struct PC {
    V30 cpu;
    uint8_t *mem;                      /* 1 MB */
    uint64_t now;                      /* CPU cycles at the start of the current slice */
    int32_t slice;                     /* cycles granted for the current slice */
    double cycle_scale;                /* emulated 8088 cycles per generated-code cycle */
    uint64_t next_frame;               /* cycle count of the next vertical retrace start */
    uint64_t frames;

    /* 8253 PIT */
    uint16_t pit_reload[3];
    uint8_t pit_rw[3], pit_lohi_next[3];
    uint16_t pit_latch; uint8_t pit_latched, pit_latch_hi;
    uint64_t pit2_start;               /* cycle when channel 2 was (re)loaded / gated on */
    uint8_t port61;

    /* speaker -> audio */
    double audio_pos;                  /* cycle position the audio has been rendered up to */
    double hp_prev_in, hp_prev_out, lp;
    int16_t audio[PC_AUDIO_MAX];
    int audio_len;
    bool sound_on;                     /* host volume mute (the game has its own Ctrl-S) */

    /* keyboard + 8259 */
    uint8_t kq[64]; int kq_head, kq_tail;
    uint8_t kbd_data;
    bool kbd_in_service;
    uint64_t kbd_next;                 /* earliest cycle for the next key IRQ */

    /* CGA */
    uint8_t cga_mode, cga_color, crtc_index, crtc[18];

    /* game port (IBM Game Control Adapter) with one joystick */
    bool joy_present;                  /* set before pc_init: reported in the equipment word */
    uint8_t joy_axis[2];               /* x, y: 0 = left/up, 128 = centre, 255 = right/down */
    uint8_t joy_buttons;               /* bit 0 = button A, bit 1 = button B (1 = pressed) */
    uint64_t joy_fired;                /* cycle of the last write to port 201h */

    /* host hooks */
    void (*on_frame)(PC *pc);          /* once per frame, at the start of vertical retrace */
    void (*on_exit)(PC *pc, int code); /* DOS exit / reboot */
    void *user;
    uint32_t stat_polls;               /* INT 1Ah calls (idle polling), for the test runner */
};

/* Load CAT.EXE (already verified) and set up memory, BIOS and CPU. */
bool pc_init(PC *pc, const uint8_t *exe, size_t exe_len, const v30_entry *entries, unsigned count);
void pc_set_tick_base(uint32_t ticks); /* BIOS time of day at power-on (18.2 Hz ticks) */
void pc_run(PC *pc);                   /* runs the game; returns never (on_exit ends the program) */

static inline uint64_t pc_time(const PC *pc) {   /* current CPU cycle */
    return pc->now + (uint64_t)((pc->slice - pc->cpu.cycles) * pc->cycle_scale);
}

void pc_key(PC *pc, uint8_t scancode, bool down);    /* XT set-1 make code */
/* 320x200 indexed (0-15 IBM RGBI colour) picture of the current CGA screen */
void pc_render(const PC *pc, uint8_t *pix320x200);
extern const uint32_t pc_rgbi_palette[16];
