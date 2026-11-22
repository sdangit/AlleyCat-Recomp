// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Syncr0ndi
/* Headless runner: plays scripted keys as fast as possible and writes screenshots / audio.
 *
 *   cat_test CAT.EXE [--frames N] [--key FRAME:SC[:LEN]]... [--shot FRAME:FILE.png]...
 *            [--wav FILE.wav] [--scale X] [--status N]
 *
 * SC is an XT scancode in hex (1C Enter, 39 Space, 48/50/4B/4D arrows, 38 Alt, 15 Y, 31 N...).
 * The key is held for LEN frames (default 3). Each status line prints a hash of video RAM. */
#include "pc.h"
extern const v30_entry cat_entries[];
extern const unsigned cat_entry_count;
extern unsigned long long v30_interp_count;
extern uint32_t cat_cov[0x10000];
#include "game_file.h"
#include "png_write.h"
#include "hand.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { long frame; uint8_t sc; int len; } KeyEv;
typedef struct { long frame; const char *file; } Shot;
static KeyEv keys[512]; static int nkeys;
static Shot shots[256]; static int nshots;
static long max_frames = 600, status_every = 0;
static const char *cov_file;
static FILE *wav; static long wav_samples;
static PC pc;

static void wav_header(FILE *f, long n) {
    uint32_t data = (uint32_t)n * 2;
    uint8_t h[44] = {'R','I','F','F',0,0,0,0,'W','A','V','E','f','m','t',' ',16,0,0,0,1,0,1,0,
                     0x44,0xAC,0,0,0x88,0x58,1,0,2,0,16,0,'d','a','t','a'};
    uint32_t riff = 36 + data;
    memcpy(h + 4, &riff, 4); memcpy(h + 40, &data, 4);
    fseek(f, 0, SEEK_SET); fwrite(h, 1, 44, f);
}

static void save_png(const char *file) {
    static uint8_t ix[320 * 200]; static uint32_t argb[320 * 200];
    pc_render(&pc, ix);
    for (int i = 0; i < 320 * 200; i++) argb[i] = 0xFF000000u | pc_rgbi_palette[ix[i]];
    if (!png_write_argb(file, argb, 320, 200, 2)) fprintf(stderr, "cannot write %s\n", file);
}

static uint32_t vram_hash(void) {
    uint32_t h = 2166136261u;
    for (int i = 0; i < 0x4000; i++) h = (h ^ pc.mem[0xB8000 + i]) * 16777619u;
    return h;
}

static void finish(int code) {
    if (cov_file) {
        FILE *cf = fopen(cov_file, "w");
        if (cf) { for (unsigned o = 0; o < 0x10000; o++) if (cat_cov[o]) fprintf(cf, "%04X %u\n", o, cat_cov[o]); fclose(cf); }
    }
    if (wav) { wav_header(wav, wav_samples); fclose(wav); }
    if (cat_hand_mode == HAND_CHECK) {
        printf("hand-written routines checked against the recompiled code:\n");
        unsigned bad = cat_hand_report(stdout);
        printf("total mismatches: %u\n", bad);
        if (bad && !code) code = 4;
    }
    printf("interpreted instructions: %llu\n", (unsigned long long)v30_interp_count);
    printf("end: frame %llu, vram %08x, CS:IP %04X:%04X\n", (unsigned long long)pc.frames, vram_hash(),
           pc.cpu.sreg[V30_CS], pc.cpu.ip);
    fflush(stdout);
    exit(code);
}

/* --autoplay SEED: random but plausible play, including menus, pauses and restarts */
static uint32_t ap_seed;
static int ap_on, ap_rooms, ap_room = -1, ap_joy;
static uint32_t ap_rand(void) { ap_seed = ap_seed * 1103515245u + 12345u; return ap_seed >> 8; }
static struct { uint8_t sc; long until; } ap_held[4];

static void autoplay(PC *p, long f) {
    for (int i = 0; i < 4; i++)
        if (ap_held[i].sc && f >= ap_held[i].until) { pc_key(p, ap_held[i].sc, false); ap_held[i].sc = 0; }
    if (ap_rand() % 6) return;                          /* new key every ~6 frames */
    static const uint8_t keys[] = {0x48, 0x50, 0x4B, 0x4D, 0x4B, 0x4D, 0x48, 0x38, 0x38, 0x38, 0x47, 0x49,
                                   0x4F, 0x51, 0x39, 0x1C};
    uint32_t r = ap_rand() % 1000;
    uint8_t sc;
    if (r < 20) sc = 0x31;                               /* N: no joystick */
    else if (r < 24) sc = 0x15;                         /* Y */
    else if (r < 44) sc = (uint8_t[]){0x25, 0x23, 0x14, 0x1E}[ap_rand() % 4];   /* skill K/H/T/A */
    else if (r < 46) sc = 0x01;                         /* Esc: pause / resume */
    else if (r < 48) {                                  /* Ctrl-R / Ctrl-S / Ctrl-M */
        pc_key(p, 0x1D, true);
        uint8_t k = (uint8_t[]){0x13, 0x1F, 0x32}[ap_rand() % 3];
        pc_key(p, k, true); pc_key(p, k, false); pc_key(p, 0x1D, false);
        return;
    } else sc = keys[ap_rand() % sizeof keys];
    for (int i = 0; i < 4; i++)
        if (!ap_held[i].sc) {
            ap_held[i].sc = sc; ap_held[i].until = f + 2 + (long)(ap_rand() % 40);
            pc_key(p, sc, true);
            break;
        }
}

static void on_frame(PC *p) {
    long f = (long)p->frames;
    if (ap_on) autoplay(p, f);
    if (ap_joy) {                                 /* the held autoplay keys also move the joystick */
        int l = 0, r = 0, u = 0, d = 0, b = 0;
        for (int i = 0; i < 4; i++) switch (ap_held[i].sc) {
            case 0x4B: l = 1; break; case 0x4D: r = 1; break; case 0x48: u = 1; break;
            case 0x50: d = 1; break; case 0x38: b = 1; break; default: break; }
        p->joy_axis[0] = l ? 10 : r ? 245 : 128;
        p->joy_axis[1] = u ? 10 : d ? 245 : 128;
        p->joy_buttons = (uint8_t)b;
    }
    /* --rooms: every 400 frames, act as if the cat had jumped through a window (test coverage) */
    static int room_pending;
    if (ap_rooms && f % 400 == 0) room_pending = 1 + (f / 400) % 5;
    if (room_pending && !cat_hand_busy()) {       /* never while a routine is being compared */
        uint8_t *ds = p->mem + ((PC_LOAD_SEG + 0x10) << 4);
        if (ap_room >= 0) {                       /* --room N: the room picker can only choose N */
            for (int i = 0x421; i < 0x432; i++) ds[i] = (uint8_t)ap_room;
            ds[0x41D] = ds[0x41E] = ds[0x41F] = ds[0x420] = 0xFF;
        }
        ds[0x551] = 1;
        if (room_pending == 5 && ap_room < 0) ds[0x418] = 1;   /* special room */
        room_pending = 0;
    }
    /* and every other time, half way, as if the room had been finished (bonus screens) */
    static int win_pending;
    if (ap_rooms && f % 800 == 600) win_pending = 1;
    if (win_pending && !cat_hand_busy()) {
        uint8_t *ds = p->mem + ((PC_LOAD_SEG + 0x10) << 4);
        if (ds[4] == 5 && !ds[5] && (f / 800) % 2 == 0) ds[0x40B1] = 1;   /* room 5: drop the cage */
        else if (ds[4] | ds[5]) ds[0x553] = 1;
        win_pending = 0;
    }
    for (int i = 0; i < nkeys; i++) {
        if (keys[i].frame == f) pc_key(p, keys[i].sc, true);
        if (keys[i].frame + keys[i].len == f) pc_key(p, keys[i].sc, false);
    }
    for (int i = 0; i < nshots; i++) if (shots[i].frame == f) save_png(shots[i].file);
    if (wav) { fwrite(p->audio, 2, (size_t)p->audio_len, wav); wav_samples += p->audio_len; }
    p->audio_len = 0;
    if (status_every && f % status_every == 0) {
        printf("frame %5ld  vram %08x  CS:IP %04X:%04X  timer polls/frame %.1f\n", f, vram_hash(),
               p->cpu.sreg[V30_CS], p->cpu.ip, (double)p->stat_polls / (double)status_every);
        p->stat_polls = 0;
    }
    if (f >= max_frames) finish(0);
}

static void on_exit_(PC *p, int code) { (void)p; printf("game exited (%d)\n", code); finish(0); }

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--capabilities")) {
#ifdef CAT_RELEASE
        puts("{\"schema_version\":1,\"runner\":\"cat_test_release\",\"build_mode\":\"release\",\"comparison_supported\":false}");
#else
        puts("{\"schema_version\":1,\"runner\":\"cat_test\",\"build_mode\":\"reference\",\"comparison_supported\":true}");
#endif
        return 0;
    }
    if (argc < 2) { fprintf(stderr, "usage: cat_test CAT.EXE [options]\n"); return 2; }
    double scale = 0;
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--frames") && i + 1 < argc) max_frames = atol(argv[++i]);
        else if (!strcmp(argv[i], "--status") && i + 1 < argc) status_every = atol(argv[++i]);
        else if (!strcmp(argv[i], "--scale") && i + 1 < argc) scale = atof(argv[++i]);
        else if (!strcmp(argv[i], "--coverage") && i + 1 < argc) cov_file = argv[++i];
        else if (!strcmp(argv[i], "--rooms")) ap_rooms = 1;
        else if (!strcmp(argv[i], "--joystick")) { ap_joy = 1; pc.joy_present = true; }
        else if (!strcmp(argv[i], "--room") && i + 1 < argc) { ap_rooms = 1; ap_room = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--autoplay") && i + 1 < argc) { ap_on = 1; ap_seed = (uint32_t)atol(argv[++i]); }
        else if (!strcmp(argv[i], "--hand-mode") && i + 1 < argc) {
            const char *m = argv[++i];
            if (!strcmp(m, "on")) cat_hand_mode = HAND_ON;
            else if (!strcmp(m, "gen")) cat_hand_mode = HAND_GEN;
            else if (!strcmp(m, "check")) cat_hand_mode = HAND_CHECK;
            else { fprintf(stderr, "unknown hand mode %s\n", m); return 2; }
#ifdef CAT_RELEASE
            if (cat_hand_mode != HAND_ON) {
                fprintf(stderr, "release runner supports only --hand-mode on; use cat_test for generated-code comparison\n");
                return 2;
            }
#endif
        }
        else if (!strcmp(argv[i], "--key") && i + 1 < argc && nkeys < 512) {
            unsigned sc; int len = 3; long fr;
            if (sscanf(argv[++i], "%ld:%x:%d", &fr, &sc, &len) >= 2) keys[nkeys++] = (KeyEv){fr, (uint8_t)sc, len};
        } else if (!strcmp(argv[i], "--shot") && i + 1 < argc && nshots < 256) {
            char *s = argv[++i], *c = strchr(s, ':');
            if (c) { *c = 0; shots[nshots++] = (Shot){atol(s), c + 1}; }
        } else if (!strcmp(argv[i], "--wav") && i + 1 < argc) {
            wav = fopen(argv[++i], "wb");
            if (wav) { uint8_t z[44] = {0}; fwrite(z, 1, 44, wav); }
        } else { fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
    }
    uint8_t *exe; size_t n;
    int rc = game_file_load(argv[1], &exe, &n);
    if (rc) { fprintf(stderr, "%s: %s\n", argv[1], rc == GAME_FILE_WRONG ? "not the known CAT.EXE" : "cannot read"); return 1; }
    pc.mem = calloc(1, 0x100000);
    pc.cycle_scale = scale;
    pc.on_frame = on_frame; pc.on_exit = on_exit_;
    pc.sound_on = true;
    pc_set_tick_base(0);
    if (!pc_init(&pc, exe, n, cat_entries, cat_entry_count)) { fprintf(stderr, "bad EXE\n"); return 1; }
    pc_run(&pc);
    return 0;
}
