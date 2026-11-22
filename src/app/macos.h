// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Syncr0ndi
#pragma once
#include <stddef.h>

/* Caller owns all UTF-8 buffers. No truncated path is returned as success. */
enum { CAT_PICK_ERROR = -1, CAT_PICK_CANCELLED = 0, CAT_PICK_SELECTED = 1 };
int cat_macos_pick_file(char *path, size_t capacity, char *error, size_t error_capacity);
int cat_macos_prepare_directory(const char *path, char *absolute, size_t capacity,
                                char *error, size_t error_capacity);
