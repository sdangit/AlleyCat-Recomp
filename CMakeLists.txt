# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Syncr0ndi
cmake_minimum_required(VERSION 3.20)

# Initialize the Mac deployment target before compiler detection. Honor explicit
# toolchain, command-line, and environment settings; use the native architecture
# unless the caller supplies CMAKE_OSX_ARCHITECTURES.
if(CMAKE_HOST_APPLE AND NOT CMAKE_TOOLCHAIN_FILE
   AND (NOT DEFINED CMAKE_SYSTEM_NAME OR CMAKE_SYSTEM_NAME STREQUAL "Darwin"))
  if(NOT DEFINED CMAKE_OSX_DEPLOYMENT_TARGET AND NOT DEFINED ENV{MACOSX_DEPLOYMENT_TARGET})
    set(CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "Minimum macOS deployment version")
  endif()
endif()
project(alleycat_recomp C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

option(CAT_BUILD_APP "Build the SDL2 game" ON)
option(CAT_BUILD_REFERENCE "Build the generated reference game and comparison runner" ON)
set(CAT_EXE "" CACHE FILEPATH "Path to the original CAT.EXE (required for reference builds)")
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)

# Privacy: never embed the build machine's folders in binaries.
if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
  add_compile_options("-ffile-prefix-map=${CMAKE_SOURCE_DIR}/=" "-ffile-prefix-map=${CMAKE_SOURCE_DIR}=.")
endif()

file(GLOB HAND_SRC CONFIGURE_DEPENDS "${CMAKE_SOURCE_DIR}/src/game/*.c")
add_library(cpu86 STATIC src/cpu/v30.c src/cpu/v30_interp.c)
target_include_directories(cpu86 PUBLIC src/cpu)

add_library(pcmachine STATIC src/pc/pc.c src/pc/font8x8.c)
target_include_directories(pcmachine PUBLIC src/pc)
target_link_libraries(pcmachine PUBLIC cpu86)
if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
  target_compile_options(pcmachine PRIVATE -Wall -Wextra)
endif()

# The release table contains only handwritten function names and addresses.
# Neither configuring nor compiling these targets needs the player's game file.
set(HAND_ENTRIES "${CMAKE_BINARY_DIR}/hand_entries.c")
add_custom_command(OUTPUT "${HAND_ENTRIES}"
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/tools/hand_entries.py"
          "${CMAKE_SOURCE_DIR}/src/game" "${HAND_ENTRIES}"
  DEPENDS ${HAND_SRC} "${CMAKE_SOURCE_DIR}/tools/hand_entries.py"
  VERBATIM)
add_library(cathand STATIC ${HAND_SRC} "${HAND_ENTRIES}")
target_include_directories(cathand PUBLIC src/game)
target_compile_definitions(cathand PUBLIC CAT_RELEASE)
target_link_libraries(cathand PUBLIC pcmachine)

set(APP_COMMON src/app/png_write.c src/app/game_file.c)
add_executable(cat_test_release src/app/test_main.c ${APP_COMMON})
target_link_libraries(cat_test_release PRIVATE cathand)

# Reference code is derived from the player's own executable and stays in the
# build directory. Keep the existing development behavior when this option is ON.
if(CAT_BUILD_REFERENCE)
  if(NOT EXISTS "${CAT_EXE}" OR IS_DIRECTORY "${CAT_EXE}")
    message(FATAL_ERROR "CAT_BUILD_REFERENCE=ON requires -DCAT_EXE=<path to your CAT.EXE>; use -DCAT_BUILD_REFERENCE=OFF for a release-only build")
  endif()
  set(GEN_DIR "${CMAKE_BINARY_DIR}/gen")
  set(GEN_TOOLS "${CMAKE_SOURCE_DIR}/tools/catrecomp.py" "${CMAKE_SOURCE_DIR}/tools/catmap.py"
                "${CMAKE_SOURCE_DIR}/tools/v30dec.py" "${CMAKE_SOURCE_DIR}/tools/liveness.py")
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${GEN_TOOLS} "${CAT_EXE}" ${HAND_SRC})
  execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_SOURCE_DIR}/tools/catrecomp.py"
                          "${CAT_EXE}" "${GEN_DIR}" --hand "${CMAKE_SOURCE_DIR}/src/game"
                  RESULT_VARIABLE gen_rc)
  if(NOT gen_rc EQUAL 0)
    message(FATAL_ERROR "Code generation failed: CAT_EXE must be the known original game file")
  endif()
  file(GLOB CAT_GEN_SRC "${GEN_DIR}/*.c")
  add_library(catgen STATIC ${CAT_GEN_SRC} ${HAND_SRC})
  target_include_directories(catgen PUBLIC "${GEN_DIR}" src/game)
  target_link_libraries(catgen PUBLIC cpu86 pcmachine)
  if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
    target_compile_options(catgen PRIVATE -Wno-unused-label -Wno-unused-variable)
  endif()
  add_executable(cat_test src/app/test_main.c ${APP_COMMON})
  target_link_libraries(cat_test PRIVATE pcmachine catgen)
endif()

if(CAT_BUILD_APP)
  if(APPLE)
    enable_language(OBJC)
  endif()
  set(SDL_SHARED OFF CACHE BOOL "" FORCE)
  set(SDL_STATIC ON CACHE BOOL "" FORCE)
  set(SDL_TEST OFF CACHE BOOL "" FORCE)
  set(SDL2_DISABLE_INSTALL ON CACHE BOOL "" FORCE)
  include(FetchContent)
  FetchContent_Declare(SDL2
    URL https://github.com/libsdl-org/SDL/releases/download/release-2.30.9/SDL2-2.30.9.tar.gz
    URL_HASH SHA256=24b574f71c87a763f50704bbb630cbe38298d544a1f890f099a4696b1d6beba4)
  FetchContent_MakeAvailable(SDL2)
  # Assertion diagnostics in SDL must not expose an external dependency-cache path.
  if(CMAKE_C_COMPILER_ID MATCHES "Clang|GNU")
    FetchContent_GetProperties(SDL2 SOURCE_DIR SDL2_PINNED_SOURCE_DIR)
    foreach(t SDL2-static SDL2main)
      if(TARGET ${t})
        target_compile_options(${t} PRIVATE "-ffile-prefix-map=${SDL2_PINNED_SOURCE_DIR}=SDL2")
      endif()
    endforeach()
  endif()

  add_executable(alleycat_release WIN32 src/app/main.c ${APP_COMMON})
  target_link_libraries(alleycat_release PRIVATE cathand SDL2::SDL2main SDL2::SDL2-static)
  if(CAT_BUILD_REFERENCE)
    add_executable(alleycat WIN32 src/app/main.c ${APP_COMMON})
    target_link_libraries(alleycat PRIVATE pcmachine catgen SDL2::SDL2main SDL2::SDL2-static)
  endif()
  if(APPLE)
    set(CAT_MACOS_BUNDLE_ID "io.github.sdangit.alleycat" CACHE STRING "macOS application bundle identifier")
    foreach(t alleycat_release alleycat)
      if(TARGET ${t})
        target_sources(${t} PRIVATE src/app/macos.m)
        target_link_libraries(${t} PRIVATE "-framework Cocoa")
        target_compile_options(${t} PRIVATE "$<$<COMPILE_LANGUAGE:OBJC>:-fobjc-arc>")
      endif()
    endforeach()
    target_sources(alleycat_release PRIVATE release/macos/AlleyCat.icns)
    set_source_files_properties(release/macos/AlleyCat.icns PROPERTIES MACOSX_PACKAGE_LOCATION Resources)
    set_target_properties(alleycat_release PROPERTIES
      MACOSX_BUNDLE TRUE
      OUTPUT_NAME "AlleyCat"
      MACOSX_BUNDLE_INFO_PLIST "${CMAKE_SOURCE_DIR}/cmake/macos/Info.plist.in")
  endif()
  if(WIN32)
    foreach(t alleycat_release alleycat)
      if(TARGET ${t})
        target_link_libraries(${t} PRIVATE comdlg32)
      endif()
    endforeach()
  endif()
endif()

if(MINGW)
  foreach(t cat_test_release cat_test alleycat_release alleycat)
    if(TARGET ${t})
      target_link_options(${t} PRIVATE -static)
    endif()
  endforeach()
  if(TARGET alleycat_release)
    target_link_options(alleycat_release PRIVATE -s)
  endif()
endif()
