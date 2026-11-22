// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Syncr0ndi
#include "macos.h"
#import <Cocoa/Cocoa.h>
#include <stdio.h>
#include <string.h>

static void set_error(char *out, size_t capacity, NSString *message) {
    if (capacity) snprintf(out, capacity, "%s", message.UTF8String ?: "Unknown macOS error");
}

static int copy_path(NSString *path, char *out, size_t capacity, char *error, size_t error_capacity) {
    const char *utf8 = path.UTF8String;
    if (!utf8 || !capacity || strlen(utf8) >= capacity) {
        set_error(error, error_capacity, @"The path cannot be represented or is too long.");
        return 0;
    }
    memcpy(out, utf8, strlen(utf8) + 1);
    return 1;
}

int cat_macos_pick_file(char *path, size_t capacity, char *error, size_t error_capacity) {
    if (capacity) path[0] = 0;
    if (error_capacity) error[0] = 0;
    @autoreleasepool {
        if (![NSThread isMainThread]) {
            set_error(error, error_capacity, @"The game file picker must run on the main thread.");
            return CAT_PICK_ERROR;
        }
        NSOpenPanel *panel = [NSOpenPanel openPanel];
        panel.title = @"Choose your original Alley Cat game file";
        panel.message = @"Select your original 1984 CAT.EXE. The game file is not included; its contents will be verified.";
        panel.canChooseFiles = YES;
        panel.canChooseDirectories = NO;
        panel.allowsMultipleSelection = NO;
        panel.resolvesAliases = YES;
        /* Filename and case are deliberately unrestricted; game_file_load verifies bytes. */
        [NSApp activateIgnoringOtherApps:YES];
        NSModalResponse response = [panel runModal];
        if (response == NSModalResponseCancel) return CAT_PICK_CANCELLED;
        if (response != NSModalResponseOK || !panel.URL.isFileURL) {
            set_error(error, error_capacity, @"The file picker did not return a local file.");
            return CAT_PICK_ERROR;
        }
        return copy_path(panel.URL.path.stringByStandardizingPath, path, capacity, error, error_capacity)
            ? CAT_PICK_SELECTED : CAT_PICK_ERROR;
    }
}

int cat_macos_prepare_directory(const char *path, char *absolute, size_t capacity,
                                char *error, size_t error_capacity) {
    if (capacity) absolute[0] = 0;
    if (error_capacity) error[0] = 0;
    @autoreleasepool {
        NSString *directory = path ? [NSString stringWithUTF8String:path] : nil;
        if (!directory || !directory.isAbsolutePath) {
            set_error(error, error_capacity, @"The state directory must be an absolute UTF-8 path.");
            return 0;
        }
        directory = directory.stringByStandardizingPath;
        if (!copy_path(directory, absolute, capacity, error, error_capacity)) return 0;
        NSError *failure = nil;
        if (![[NSFileManager defaultManager] createDirectoryAtPath:directory
                                      withIntermediateDirectories:YES attributes:nil error:&failure]) {
            set_error(error, error_capacity, failure.localizedDescription);
            return 0;
        }
        BOOL is_directory = NO;
        if (![[NSFileManager defaultManager] fileExistsAtPath:directory isDirectory:&is_directory] || !is_directory) {
            set_error(error, error_capacity, @"The state path is not a directory.");
            return 0;
        }
        return 1;
    }
}
