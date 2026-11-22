// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Syncr0ndi
/* Alley Cat: SDL2 front end around the recompiled game.
 *
 * Finds the player's CAT.EXE (command line, alleycat.ini, next to the program, or a file
 * picker), checks it, and runs it on the PC model at the speed of a 4.77 MHz IBM PC.
 * Keys: the game's own (arrows, Alt, Esc, Ctrl-S/R/M, letters). F11 or Alt+Enter: full screen.
 * F12: screenshot (PNG next to the program). Window close: quit. */
#include "pc.h"
extern const v30_entry cat_entries[];   /* the game's routines (hand-written; or recompiled in dev builds) */
extern const unsigned cat_entry_count;
#include "game_file.h"
#include "png_write.h"
#include <SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <limits.h>
#ifdef __APPLE__
#include "macos.h"
#endif
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commdlg.h>
#endif

#define PRESCALE 4                        /* crisp integer upscale, then smooth to the window */

static PC pc;
static SDL_Window *win;
static SDL_Renderer *ren;
static SDL_Texture *tex, *big;
static SDL_AudioDeviceID audio;
static uint64_t perf_freq, next_deadline;
static double frame_ticks;
#define PATH_CAP 4096
static char base_dir[PATH_CAP], state_dir[PATH_CAP], shot_dir[PATH_CAP], log_dir[PATH_CAP];
static char ini_path[PATH_CAP];
static uint8_t held[128];
static long selftest_frames;
static SDL_GameController *pad;
static uint8_t pad_keys[4];                       /* arrows held through the D-pad */

static void quit_now(int code);
static void msg(const char *text) { SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_INFORMATION, "Alley Cat", text, win); }
static void report_error(const char *text) {
    fprintf(stderr, "Alley Cat: %s\n", text);
    if (!selftest_frames) SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Alley Cat", text, win);
}
static bool copy_text(char *out, size_t n, const char *text) {
    size_t len = strlen(text);
    if (len >= n) return false;
    memcpy(out, text, len + 1);
    return true;
}
static bool path_join(char *out, size_t n, const char *directory, const char *name) {
    size_t len = strlen(directory);
    const char *sep = len && directory[len - 1] != '/' && directory[len - 1] != '\\' ? "/" : "";
    int written = snprintf(out, n, "%s%s%s", directory, sep, name);
    return written >= 0 && (size_t)written < n;
}

static bool init_paths(void) {
    char *base = SDL_GetBasePath();
    bool ok = copy_text(base_dir, sizeof base_dir, base ? base : "");
    SDL_free(base);
    if (!ok) { report_error("The application path is too long."); return false; }
#ifdef __APPLE__
    const char *override = getenv("ALLEYCAT_STATE_DIR");
    char *pref = override ? NULL : SDL_GetPrefPath("sdangit", "AlleyCat");
    char error[1024], directory[PATH_CAP];
    if (!cat_macos_prepare_directory(override ? override : pref, state_dir, sizeof state_dir, error, sizeof error)) {
        SDL_free(pref); report_error(error); return false;
    }
    SDL_free(pref);
    if (!path_join(directory, sizeof directory, state_dir, "screenshots") ||
        !cat_macos_prepare_directory(directory, shot_dir, sizeof shot_dir, error, sizeof error)) {
        report_error("Cannot create the screenshot directory in the application state directory."); return false;
    }
    if (!path_join(directory, sizeof directory, state_dir, "logs") ||
        !cat_macos_prepare_directory(directory, log_dir, sizeof log_dir, error, sizeof error)) {
        report_error("Cannot create the log directory in the application state directory."); return false;
    }
#else
    /* Keep the established executable-relative layout on Windows and other hosts. */
    copy_text(state_dir, sizeof state_dir, base_dir);
    copy_text(shot_dir, sizeof shot_dir, base_dir);
    copy_text(log_dir, sizeof log_dir, base_dir);
#endif
    if (!path_join(ini_path, sizeof ini_path, state_dir, "alleycat.ini")) {
        report_error("The settings path is too long."); return false;
    }
    return true;
}

/* game controller: the left stick / D-pad is the PC joystick (game port), A and B its buttons;
 * the D-pad, A and Start also press the arrow keys, Alt and Esc for keyboard mode */
static void pad_update(void) {
    if (!pad) return;
    int x = SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_LEFTX);
    int y = SDL_GameControllerGetAxis(pad, SDL_CONTROLLER_AXIS_LEFTY);
    int l = SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_DPAD_LEFT);
    int r = SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_DPAD_RIGHT);
    int u = SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_DPAD_UP);
    int d = SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_DPAD_DOWN);
    if (l) x = -32768; else if (r) x = 32767;
    if (u) y = -32768; else if (d) y = 32767;
    pc.joy_axis[0] = (uint8_t)((x + 32768) >> 8);
    pc.joy_axis[1] = (uint8_t)((y + 32768) >> 8);
    pc.joy_buttons = (uint8_t)(SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_A) |
                               SDL_GameControllerGetButton(pad, SDL_CONTROLLER_BUTTON_B) << 1);
    const uint8_t sc[4] = {0x4B, 0x4D, 0x48, 0x50};
    const int now[4] = {l || x < -16000, r || x > 16000, u || y < -16000, d || y > 16000};
    for (int i = 0; i < 4; i++)
        if (now[i] != pad_keys[i]) { pad_keys[i] = (uint8_t)now[i]; pc_key(&pc, sc[i], now[i] != 0); }
}

/* ---------------------------------------------------------------- keyboard: SDL -> XT set 1 */
static uint8_t xt_code(SDL_Scancode s) {
    if (s >= SDL_SCANCODE_A && s <= SDL_SCANCODE_Z) {
        static const uint8_t az[26] = {0x1E,0x30,0x2E,0x20,0x12,0x21,0x22,0x23,0x17,0x24,0x25,0x26,0x32,
                                       0x31,0x18,0x19,0x10,0x13,0x1F,0x14,0x16,0x2F,0x11,0x2D,0x15,0x2C};
        return az[s - SDL_SCANCODE_A];
    }
    if (s >= SDL_SCANCODE_1 && s <= SDL_SCANCODE_9) return (uint8_t)(0x02 + (s - SDL_SCANCODE_1));
    if (s >= SDL_SCANCODE_F1 && s <= SDL_SCANCODE_F10) return (uint8_t)(0x3B + (s - SDL_SCANCODE_F1));
    switch (s) {
    case SDL_SCANCODE_0: return 0x0B;          case SDL_SCANCODE_MINUS: return 0x0C;
    case SDL_SCANCODE_EQUALS: return 0x0D;     case SDL_SCANCODE_BACKSPACE: return 0x0E;
    case SDL_SCANCODE_TAB: return 0x0F;        case SDL_SCANCODE_LEFTBRACKET: return 0x1A;
    case SDL_SCANCODE_RIGHTBRACKET: return 0x1B; case SDL_SCANCODE_RETURN: case SDL_SCANCODE_KP_ENTER: return 0x1C;
    case SDL_SCANCODE_LCTRL: case SDL_SCANCODE_RCTRL: return 0x1D;
    case SDL_SCANCODE_SEMICOLON: return 0x27;  case SDL_SCANCODE_APOSTROPHE: return 0x28;
    case SDL_SCANCODE_GRAVE: return 0x29;      case SDL_SCANCODE_LSHIFT: return 0x2A;
    case SDL_SCANCODE_BACKSLASH: return 0x2B;  case SDL_SCANCODE_COMMA: return 0x33;
    case SDL_SCANCODE_PERIOD: return 0x34;     case SDL_SCANCODE_SLASH: return 0x35;
    case SDL_SCANCODE_RSHIFT: return 0x36;     case SDL_SCANCODE_KP_MULTIPLY: return 0x37;
    case SDL_SCANCODE_LALT: case SDL_SCANCODE_RALT: return 0x38;
    case SDL_SCANCODE_SPACE: return 0x39;      case SDL_SCANCODE_ESCAPE: return 0x01;
    case SDL_SCANCODE_HOME: case SDL_SCANCODE_KP_7: return 0x47;
    case SDL_SCANCODE_UP: case SDL_SCANCODE_KP_8: return 0x48;
    case SDL_SCANCODE_PAGEUP: case SDL_SCANCODE_KP_9: return 0x49;
    case SDL_SCANCODE_KP_MINUS: return 0x4A;
    case SDL_SCANCODE_LEFT: case SDL_SCANCODE_KP_4: return 0x4B;
    case SDL_SCANCODE_KP_5: return 0x4C;
    case SDL_SCANCODE_RIGHT: case SDL_SCANCODE_KP_6: return 0x4D;
    case SDL_SCANCODE_KP_PLUS: return 0x4E;
    case SDL_SCANCODE_END: case SDL_SCANCODE_KP_1: return 0x4F;
    case SDL_SCANCODE_DOWN: case SDL_SCANCODE_KP_2: return 0x50;
    case SDL_SCANCODE_PAGEDOWN: case SDL_SCANCODE_KP_3: return 0x51;
    case SDL_SCANCODE_INSERT: case SDL_SCANCODE_KP_0: return 0x52;
    case SDL_SCANCODE_DELETE: case SDL_SCANCODE_KP_PERIOD: return 0x53;
    default: return 0;
    }
}

static void release_all(void) {
    for (int i = 1; i < 128; i++) if (held[i]) { held[i] = 0; pc_key(&pc, (uint8_t)i, false); }
}

/* ---------------------------------------------------------------- video */
static void present(void) {
    static uint8_t ix[320 * 200];
    void *pixels; int pitch;
    pc_render(&pc, ix);
    if (SDL_LockTexture(tex, NULL, &pixels, &pitch) != 0) {
        report_error(SDL_GetError()); quit_now(1);
    }
    for (int y = 0; y < 200; y++) {
        uint32_t *row = (uint32_t *)((uint8_t *)pixels + y * pitch);
        for (int x = 0; x < 320; x++) row[x] = 0xFF000000u | pc_rgbi_palette[ix[y * 320 + x]];
    }
    SDL_UnlockTexture(tex);
    int w = 0, h = 0;
    if (SDL_SetRenderTarget(ren, big) != 0 || SDL_RenderCopy(ren, tex, NULL, NULL) != 0 ||
        SDL_SetRenderTarget(ren, NULL) != 0 || SDL_SetRenderDrawColor(ren, 0, 0, 0, 255) != 0 ||
        SDL_RenderClear(ren) != 0 || SDL_GetRendererOutputSize(ren, &w, &h) != 0 || w <= 0 || h <= 0) {
        report_error("Could not render the game frame."); quit_now(1);
    }
    int dw = w, dh = w * 3 / 4;                         /* 4:3 picture, as on a CRT */
    if (dh > h) { dh = h; dw = h * 4 / 3; }
    SDL_Rect dst = {(w - dw) / 2, (h - dh) / 2, dw, dh};
    if (SDL_RenderCopy(ren, big, NULL, &dst) != 0) { report_error(SDL_GetError()); quit_now(1); }
    if (selftest_frames && (long)pc.frames >= selftest_frames) {
        char path[PATH_CAP];
        if (w > INT_MAX / 4 || (size_t)h > SIZE_MAX / ((size_t)w * 4) ||
            !path_join(path, sizeof path, shot_dir, "alleycat_selftest.png")) {
            report_error("Self-test image dimensions or path are too large."); quit_now(1);
        }
        uint32_t *px = malloc((size_t)w * h * 4);
        bool saved = px && SDL_RenderReadPixels(ren, NULL, SDL_PIXELFORMAT_ARGB8888, px, w * 4) == 0 &&
                     png_write_argb(path, px, w, h, 1);
        free(px);
        if (!saved) { report_error("Self-test image could not be read or written."); quit_now(1); }
        printf("selftest image: %s\n", path);
        quit_now(0);
    }
    SDL_RenderPresent(ren);
}

static void screenshot(void) {
    static uint8_t ix[320 * 200]; static uint32_t argb[320 * 200];
    char path[PATH_CAP], name[32];
    pc_render(&pc, ix);
    for (int i = 0; i < 320 * 200; i++) argb[i] = 0xFF000000u | pc_rgbi_palette[ix[i]];
    for (int i = 1; i < 10000; i++) {
        snprintf(name, sizeof name, "alleycat_%04d.png", i);
        if (!path_join(path, sizeof path, shot_dir, name)) break;
        FILE *f = fopen(path, "rb");
        if (f) { fclose(f); continue; }
        if (!png_write_argb(path, argb, 320, 200, 3)) report_error("The screenshot could not be written.");
        else printf("screenshot: %s\n", path);
        return;
    }
    report_error("No available screenshot filename could be created.");
}

/* ---------------------------------------------------------------- per-frame host work */
static void quit_now(int code) {
    if (audio) SDL_CloseAudioDevice(audio);
    SDL_Quit();
    exit(code);
}

static void poll_events(void) {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        switch (e.type) {
        case SDL_CONTROLLERDEVICEADDED:
            if (!pad) pad = SDL_GameControllerOpen(e.cdevice.which);
            break;
        case SDL_CONTROLLERBUTTONDOWN: case SDL_CONTROLLERBUTTONUP: {
            uint8_t sc = e.cbutton.button == SDL_CONTROLLER_BUTTON_A ? 0x38 :
                         e.cbutton.button == SDL_CONTROLLER_BUTTON_START ? 0x01 : 0;
            if (sc) pc_key(&pc, sc, e.type == SDL_CONTROLLERBUTTONDOWN);
            break;
        }
        case SDL_QUIT: quit_now(0); break;
        case SDL_WINDOWEVENT:
            if (e.window.event == SDL_WINDOWEVENT_FOCUS_LOST) release_all();
            break;
        case SDL_KEYDOWN: case SDL_KEYUP: {
            bool down = e.type == SDL_KEYDOWN;
            SDL_Scancode s = e.key.keysym.scancode;
            if (down && (s == SDL_SCANCODE_F11 || (s == SDL_SCANCODE_RETURN && (e.key.keysym.mod & KMOD_ALT)))) {
                bool fs = SDL_GetWindowFlags(win) & SDL_WINDOW_FULLSCREEN_DESKTOP;
                SDL_SetWindowFullscreen(win, fs ? 0 : SDL_WINDOW_FULLSCREEN_DESKTOP);
                SDL_ShowCursor(fs ? SDL_ENABLE : SDL_DISABLE);
                break;
            }
            if (down && s == SDL_SCANCODE_F12) { screenshot(); break; }
            uint8_t sc = xt_code(s);
            if (!sc) break;
            if (down) { held[sc] = 1; pc_key(&pc, sc, true); }    /* repeats act like typematic */
            else if (held[sc]) { held[sc] = 0; pc_key(&pc, sc, false); }
            break;
        }
        default: break;
        }
    }
}

static void on_frame(PC *p) {
    poll_events();
    pad_update();
    present();
    /* audio: keep 40-120 ms queued; trim or pad if the clocks drift apart */
    if (audio) {
        uint32_t q = SDL_GetQueuedAudioSize(audio) / 2;
        if (q < PC_AUDIO_RATE / 50) {
            static int16_t pad[PC_AUDIO_RATE / 25];
            SDL_QueueAudio(audio, pad, sizeof pad);
        }
        if (q < PC_AUDIO_RATE / 8) SDL_QueueAudio(audio, p->audio, (uint32_t)p->audio_len * 2);
    }
    p->audio_len = 0;
    /* pace to real time: one CGA frame = 1/59.92 s */
    uint64_t now = SDL_GetPerformanceCounter();
    next_deadline += (uint64_t)frame_ticks;
    if (now > next_deadline + perf_freq / 4) next_deadline = now;          /* fell behind (e.g. window drag) */
    while ((now = SDL_GetPerformanceCounter()) < next_deadline) {
        uint64_t left_ms = (next_deadline - now) * 1000 / perf_freq;
        if (left_ms > 2) SDL_Delay((uint32_t)(left_ms - 1));
    }
}

static void on_exit_(PC *p, int code) { (void)p; quit_now(code); }

static void on_fatal(const char *report) {
    char path[PATH_CAP], message[PATH_CAP + 128];
    bool saved = false;
    if (path_join(path, sizeof path, log_dir, "alleycat_crash.log")) {
        FILE *f = fopen(path, "w");
        if (f) {
            saved = fputs(report, f) >= 0;
            if (fclose(f) != 0) saved = false;
        }
    }
    if (saved) snprintf(message, sizeof message, "The game hit an internal error. Details were saved to:\n%s", path);
    else copy_text(message, sizeof message, "The game hit an internal error. Its diagnostic log could not be saved; details were written to stderr.");
    report_error(message);
}

/* ---------------------------------------------------------------- finding CAT.EXE */
static void read_ini(char *game, size_t n) {
    game[0] = 0;
    FILE *f = fopen(ini_path, "r");
    if (!f) return;
    char line[PATH_CAP + 8];
    while (fgets(line, sizeof line, f)) {
        if (!strchr(line, '\n') && !feof(f)) { game[0] = 0; break; }
        if (!strncmp(line, "game=", 5)) {
            line[strcspn(line, "\r\n")] = 0;
            if (!copy_text(game, n, line + 5)) { game[0] = 0; break; }
        }
    }
    fclose(f);
}

static bool write_ini(const char *game) {
    if (strpbrk(game, "\r\n")) { report_error("The game path contains a newline and cannot be saved in settings."); return false; }
    FILE *f = fopen(ini_path, "w");
    bool saved = false;
    if (f) {
        saved = fprintf(f, "; Alley Cat\n; game = path to your original CAT.EXE (read at every start)\ngame=%s\n", game) >= 0;
        if (fclose(f) != 0) saved = false;
    }
    if (!saved) report_error("The game location could not be saved in alleycat.ini. You may need to select it again next time.");
    return saved;
}

static int pick_file(char *out, size_t n) {
#ifdef __APPLE__
    char error[1024];
    int result = cat_macos_pick_file(out, n, error, sizeof error);
    if (result == CAT_PICK_ERROR) report_error(error);
    return result;
#elif defined(_WIN32)
    OPENFILENAMEA ofn;
    memset(&ofn, 0, sizeof ofn);
    out[0] = 0;
    ofn.lStructSize = sizeof ofn;
    ofn.lpstrFilter = "Alley Cat (CAT.EXE)\0CAT.EXE\0All files\0*.*\0";
    ofn.lpstrFile = out; ofn.nMaxFile = (DWORD)n;
    ofn.lpstrTitle = "Where is your Alley Cat CAT.EXE?";
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
    return GetOpenFileNameA(&ofn) ? 1 : 0;
#else
    (void)out; (void)n; return 0;
#endif
}

/* 1: ready, 0: user cancelled, -1: failure. */
static int find_game(const char *explicit_path, uint8_t **exe, size_t *len) {
    char cand[PATH_CAP];
    if (explicit_path) {
        int rc = game_file_load(explicit_path, exe, len);
        if (rc == GAME_FILE_OK) return 1;
        report_error(rc == GAME_FILE_WRONG ? "The specified file is not the known original CAT.EXE (55,067 bytes, August 1984)."
                                          : "The specified game file could not be read.");
        return -1;
    }
    read_ini(cand, sizeof cand);
    if (cand[0] && game_file_load(cand, exe, len) == GAME_FILE_OK) return 1;
    if (path_join(cand, sizeof cand, base_dir, "CAT.EXE") && game_file_load(cand, exe, len) == GAME_FILE_OK) {
        write_ini(cand); return 1;
    }
    if (selftest_frames) { report_error("Self-test requires a valid game path or saved game location."); return -1; }
#ifndef __APPLE__
    msg("This program needs the original Alley Cat game file, CAT.EXE (1984).\n"
        "It is not included. Please choose your copy in the next window.\n"
        "Its location is saved in alleycat.ini.");
#endif
    for (;;) {
        int picked = pick_file(cand, sizeof cand);
        if (picked <= 0) return picked;
        int rc = game_file_load(cand, exe, len);
        if (rc == GAME_FILE_OK) { write_ini(cand); return 1; }
        msg(rc == GAME_FILE_WRONG ? "That file is not the known CAT.EXE (55,067 bytes, August 1984). Please try another."
                                  : "That file could not be read. Please try another.");
    }
}

static bool parse_args(int argc, char **argv, const char **game) {
    *game = NULL;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--selftest")) {
            if (++i >= argc) { fprintf(stderr, "--selftest requires a positive frame count\n"); return false; }
            errno = 0; char *end;
            long frames = strtol(argv[i], &end, 10);
            if (errno || *end || frames <= 0) { fprintf(stderr, "invalid self-test frame count\n"); return false; }
            selftest_frames = frames;
        } else if (argv[i][0] != '-' && !*game) *game = argv[i];
        else { fprintf(stderr, "usage: alleycat [CAT.EXE] [--selftest FRAMES]\n"); return false; }
    }
    return true;
}

int main(int argc, char **argv) {
    const char *game;
    if (!parse_args(argc, argv, &game)) return 2;
    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_EVENTS | SDL_INIT_GAMECONTROLLER) != 0) { fprintf(stderr, "SDL: %s\n", SDL_GetError()); return 1; }
    if (!init_paths()) { SDL_Quit(); return 1; }
    uint8_t *exe; size_t len;
    int found = find_game(game, &exe, &len);
    if (found <= 0) {
        SDL_Quit();
#ifdef __APPLE__
        return found == 0 ? 0 : 1;
#else
        return 1;
#endif
    }

    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "0");
    win = SDL_CreateWindow("Alley Cat", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, 1280, 960,
                           SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI);
    if (!win) { report_error(SDL_GetError()); free(exe); quit_now(1); }
    ren = SDL_CreateRenderer(win, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_TARGETTEXTURE);
    if (!ren) { report_error(SDL_GetError()); free(exe); quit_now(1); }
    SDL_SetWindowMinimumSize(win, 320, 240);
    tex = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, 320, 200);
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "1");
    big = SDL_CreateTexture(ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_TARGET, 320 * PRESCALE, 200 * PRESCALE);
    if (!tex || !big) { report_error(SDL_GetError()); free(exe); quit_now(1); }

    SDL_AudioSpec want = {0}, have;
    want.freq = PC_AUDIO_RATE; want.format = AUDIO_S16SYS; want.channels = 1; want.samples = 512;
    audio = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
    if (audio) SDL_PauseAudioDevice(audio, 0);
    else fprintf(stderr, "Audio unavailable: %s\n", SDL_GetError());

    perf_freq = SDL_GetPerformanceFrequency();
    frame_ticks = (double)perf_freq * PC_FRAME_CYC / PC_CPU_HZ;
    next_deadline = SDL_GetPerformanceCounter();

    pc.mem = calloc(1, 0x100000);
    if (!pc.mem) { report_error("Could not allocate game memory."); free(exe); quit_now(1); }
    pc.on_frame = on_frame; pc.on_exit = on_exit_;
    for (int i = 0; i < SDL_NumJoysticks() && !pad; i++)
        if (SDL_IsGameController(i)) pad = SDL_GameControllerOpen(i);
    pc.joy_present = pad != NULL;                      /* a game port with a joystick, if there is a pad */
    pc.sound_on = true;
    {   /* BIOS clock starts at the current time of day, as on a real PC after DOS set it */
        time_t t = time(NULL); struct tm *lt = localtime(&t);
        double secs = lt ? lt->tm_hour * 3600.0 + lt->tm_min * 60.0 + lt->tm_sec : 0;
        pc_set_tick_base((uint32_t)(secs * 1193182.0 / 65536.0));
    }
    if (!pc_init(&pc, exe, len, cat_entries, cat_entry_count)) { report_error("CAT.EXE could not be loaded."); free(exe); quit_now(1); }
    free(exe);
    v30_fatal_hook = on_fatal;
    pc_run(&pc);
    return 0;
}
