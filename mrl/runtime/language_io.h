#ifndef MRL_LANGUAGE_IO_H
#define MRL_LANGUAGE_IO_H

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <io.h>
#include <wchar.h>
#include <sys/stat.h>
#include <fcntl.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

/* File and argument strings are deliberately bounded at 32 MiB. */
#ifndef MRL_IO_MAX_BYTES
#define MRL_IO_MAX_BYTES (32u * 1024u * 1024u)
#endif

typedef struct {
    bool ok;
    char *value;
    const char *error;
} MrlIoStringResult;

static int mrl_io_saved_argc;
static char **mrl_io_saved_argv;
static unsigned mrl_io_temp_counter;
#if defined(_WIN32)
static int mrl_io_wide_argc;
static char **mrl_io_wide_argv;
#endif

static bool mrl_io_utf8(const unsigned char *bytes, size_t length);

#if defined(_WIN32)
static wchar_t *mrl_io_wide(const char *path) {
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (!count) return NULL;
    wchar_t *wide = (wchar_t *)malloc((size_t)count * sizeof(*wide));
    if (!wide || !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, count)) { free(wide); return NULL; }
    return wide;
}
static FILE *mrl_io_open(const char *path, const char *mode) {
    wchar_t *wide_path = mrl_io_wide(path);
    if (!wide_path) return NULL;
    wchar_t wide_mode[3] = {L'r', L'b', L'\0'};
    if (mode[0] == 'w') wide_mode[0] = L'w';
    FILE *file = _wfopen(wide_path, wide_mode);
    free(wide_path);
    return file;
}
static void mrl_io_remove(const char *path) {
    wchar_t *wide_path = mrl_io_wide(path);
    if (wide_path) DeleteFileW(wide_path);
    free(wide_path);
}
static bool mrl_io_replace(const char *from, const char *to) {
    wchar_t *wide_from = mrl_io_wide(from), *wide_to = mrl_io_wide(to);
    BOOL ok = wide_from && wide_to && MoveFileExW(wide_from, wide_to, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    free(wide_from); free(wide_to);
    return ok != 0;
}
static bool mrl_io_sync(FILE *file) { return fflush(file) == 0 && _commit(_fileno(file)) == 0; }
#else
static FILE *mrl_io_open(const char *path, const char *mode) { return fopen(path, mode); }
static void mrl_io_remove(const char *path) { remove(path); }
static bool mrl_io_replace(const char *from, const char *to) { return rename(from, to) == 0; }
static bool mrl_io_sync(FILE *file) { return fflush(file) == 0 && fsync(fileno(file)) == 0; }
#endif

#if defined(_WIN32)
static void mrl_io_free_wide_argv(void) {
    if (mrl_io_wide_argv) {
        for (int index = 0; index < mrl_io_wide_argc; ++index) free(mrl_io_wide_argv[index]);
        free(mrl_io_wide_argv);
    }
    mrl_io_wide_argv = NULL;
    mrl_io_wide_argc = 0;
}
static bool mrl_io_load_wide_argv(void) {
    mrl_io_free_wide_argv();
    const wchar_t *command = GetCommandLineW();
    if (!command) return false;
    /* CommandLineToArgvW is the platform parser.  Reimplementing its quote and
       backslash rules loses empty arguments and escaped quotes on Windows. */
    typedef LPWSTR *(WINAPI *MrlCommandLineToArgvW)(LPCWSTR, int *);
    HMODULE shell = LoadLibraryW(L"Shell32.dll");
    if (!shell) return false;
    MrlCommandLineToArgvW parse = (MrlCommandLineToArgvW)GetProcAddress(shell, "CommandLineToArgvW");
    if (!parse) { FreeLibrary(shell); return false; }
    int count = 0;
    LPWSTR *wide_values = parse(command, &count);
    if (!wide_values || count < 0) {
        if (wide_values) LocalFree(wide_values);
        FreeLibrary(shell);
        return false;
    }
    char **values = (char **)calloc((size_t)count, sizeof(*values));
    if (count && !values) {
        LocalFree(wide_values);
        FreeLibrary(shell);
        return false;
    }
    mrl_io_wide_argv = values;
    for (int index = 0; index < count; ++index) {
        int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_values[index], -1, NULL, 0, NULL, NULL);
        if (!bytes) { LocalFree(wide_values); FreeLibrary(shell); mrl_io_free_wide_argv(); return false; }
        values[index] = (char *)malloc((size_t)bytes);
        if (!values[index] || !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide_values[index], -1, values[index], bytes, NULL, NULL)) {
            LocalFree(wide_values);
            FreeLibrary(shell);
            mrl_io_wide_argc = index + 1;
            mrl_io_free_wide_argv();
            return false;
        }
        mrl_io_wide_argc = index + 1;
    }
    LocalFree(wide_values);
    FreeLibrary(shell);
    return true;
}
#endif

static bool mrl_io_validate(const unsigned char *bytes, size_t length, const char **error) {
    for (size_t index = 0; index < length; ++index) if (!bytes[index]) { if (error) *error = "io input contains NUL"; return false; }
    if (!mrl_io_utf8(bytes, length)) { if (error) *error = "io input is not valid UTF-8"; return false; }
    return true;
}

static bool mrl_io_utf8(const unsigned char *bytes, size_t length) {
    size_t index = 0;
    while (index < length) {
        unsigned char first = bytes[index++];
        if (first < 0x80) continue;
        if (first >= 0xc2 && first <= 0xdf) {
            if (index >= length || (bytes[index++] & 0xc0) != 0x80) return false;
            continue;
        }
        if (first == 0xe0) {
            if (index + 1 >= length || bytes[index] < 0xa0 || bytes[index] > 0xbf || (bytes[index + 1] & 0xc0) != 0x80) return false;
            index += 2;
            continue;
        }
        if ((first >= 0xe1 && first <= 0xec) || (first >= 0xee && first <= 0xef)) {
            if (index + 1 >= length || (bytes[index] & 0xc0) != 0x80 || (bytes[index + 1] & 0xc0) != 0x80) return false;
            index += 2;
            continue;
        }
        if (first == 0xed) {
            if (index + 1 >= length || bytes[index] < 0x80 || bytes[index] > 0x9f || (bytes[index + 1] & 0xc0) != 0x80) return false;
            index += 2;
            continue;
        }
        if (first == 0xf0) {
            if (index + 2 >= length || bytes[index] < 0x90 || bytes[index] > 0xbf || (bytes[index + 1] & 0xc0) != 0x80 || (bytes[index + 2] & 0xc0) != 0x80) return false;
            index += 3;
            continue;
        }
        if (first >= 0xf1 && first <= 0xf3) {
            if (index + 2 >= length || (bytes[index] & 0xc0) != 0x80 || (bytes[index + 1] & 0xc0) != 0x80 || (bytes[index + 2] & 0xc0) != 0x80) return false;
            index += 3;
            continue;
        }
        if (first == 0xf4) {
            if (index + 2 >= length || bytes[index] < 0x80 || bytes[index] > 0x8f || (bytes[index + 1] & 0xc0) != 0x80 || (bytes[index + 2] & 0xc0) != 0x80) return false;
            index += 3;
            continue;
        }
        return false;
    }
    return true;
}

static MrlIoStringResult mrl_io_error(const char *error) {
    return (MrlIoStringResult){false, NULL, error};
}

static MrlIoStringResult mrl_io_copy(const unsigned char *bytes, size_t length) {
    if (length > MRL_IO_MAX_BYTES) return mrl_io_error("io input too large");
    const char *error = NULL;
    if (!mrl_io_validate(bytes, length, &error)) return mrl_io_error(error);
    char *value = (char *)malloc(length + 1);
    if (!value) return mrl_io_error("io string allocation failed");
    if (length) memcpy(value, bytes, length);
    value[length] = '\0';
    return (MrlIoStringResult){true, value, NULL};
}

static void mrl_io_string_release(char *value) { free(value); }

static void mrl_io_cleanup_argv(void) {
#if defined(_WIN32)
    mrl_io_free_wide_argv();
#endif
    mrl_io_saved_argc = 0;
    mrl_io_saved_argv = NULL;
}

static void mrl_io_set_argv(int argc, char **argv) {
#if defined(_WIN32)
    if (mrl_io_load_wide_argv()) return;
#endif
    mrl_io_saved_argc = argc < 0 ? 0 : argc;
    mrl_io_saved_argv = argv;
}

static int32_t mrl_io_argc(void) {
#if defined(_WIN32)
    return mrl_io_wide_argc > INT32_MAX ? INT32_MAX : (int32_t)mrl_io_wide_argc;
#else
    return mrl_io_saved_argc > INT32_MAX ? INT32_MAX : (int32_t)mrl_io_saved_argc;
#endif
}

static MrlIoStringResult mrl_io_argv(int32_t index) {
#if defined(_WIN32)
    if (index < 0 || index >= mrl_io_wide_argc || !mrl_io_wide_argv || !mrl_io_wide_argv[index]) return mrl_io_error("io argv index out of range");
    const char *argument = mrl_io_wide_argv[index];
#else
    if (index < 0 || index >= mrl_io_saved_argc || !mrl_io_saved_argv || !mrl_io_saved_argv[index]) return mrl_io_error("io argv index out of range");
    const char *argument = mrl_io_saved_argv[index];
#endif
    size_t length = 0;
    while (length <= MRL_IO_MAX_BYTES && argument[length]) ++length;
    if (length > MRL_IO_MAX_BYTES) return mrl_io_error("io argv too large");
    return mrl_io_copy((const unsigned char *)argument, length);
}

static FILE *mrl_io_open_temp(const char *path, char **temporary) {
    size_t length = strlen(path);
    if (length > MRL_IO_MAX_BYTES - 48) return NULL;
    char *candidate = (char *)malloc(length + 48);
    if (!candidate) return NULL;
#if defined(_WIN32)
    unsigned long process = (unsigned long)GetCurrentProcessId();
#else
    unsigned long process = (unsigned long)getpid();
#endif
    for (unsigned attempt = 0; attempt < 1000; ++attempt) {
        snprintf(candidate, length + 48, "%s.mrl-tmp-%lu-%u", path, process, ++mrl_io_temp_counter);
#if defined(_WIN32)
        wchar_t *wide = mrl_io_wide(candidate);
        int descriptor = wide ? _wopen(wide, _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY, _S_IREAD | _S_IWRITE) : -1;
        free(wide);
#else
        int descriptor = open(candidate, O_WRONLY | O_CREAT | O_EXCL, 0600);
#endif
        if (descriptor >= 0) {
#if defined(_WIN32)
            FILE *file = _fdopen(descriptor, "wb");
#else
            FILE *file = fdopen(descriptor, "wb");
#endif
            if (!file) {
#if defined(_WIN32)
                _close(descriptor);
#else
                close(descriptor);
#endif
                mrl_io_remove(candidate); free(candidate); return NULL;
            }
            *temporary = candidate;
            return file;
        }
        if (errno != EEXIST) break;
    }
    free(candidate);
    return NULL;
}

static MrlIoStringResult mrl_io_read_utf8(const char *path) {
    if (!path || !*path) return mrl_io_error("io read path is empty");
    size_t path_length = strlen(path);
    const char *path_error = NULL;
    if (path_length > MRL_IO_MAX_BYTES || !mrl_io_validate((const unsigned char *)path, path_length, &path_error)) return mrl_io_error(path_error ? path_error : "io read path is invalid");
    FILE *file = mrl_io_open(path, "rb");
    if (!file) return mrl_io_error("io read open failed");
    size_t length = 0, capacity = 4096;
    unsigned char *bytes = (unsigned char *)malloc(capacity);
    if (!bytes) { fclose(file); return mrl_io_error("io read allocation failed"); }
    for (;;) {
        if (length == capacity) {
            if (capacity > MRL_IO_MAX_BYTES / 2) capacity = MRL_IO_MAX_BYTES;
            else capacity *= 2;
            if (capacity <= length) { free(bytes); fclose(file); return mrl_io_error("io input too large"); }
            unsigned char *grown = (unsigned char *)realloc(bytes, capacity);
            if (!grown) { free(bytes); fclose(file); return mrl_io_error("io read allocation failed"); }
            bytes = grown;
        }
        size_t count = fread(bytes + length, 1, capacity - length, file);
        length += count;
        if (ferror(file)) { free(bytes); fclose(file); return mrl_io_error("io read failed"); }
        if (feof(file)) break;
        if (length == MRL_IO_MAX_BYTES) {
            int next = fgetc(file);
            if (next != EOF) { free(bytes); fclose(file); return mrl_io_error("io input too large"); }
            if (ferror(file)) { free(bytes); fclose(file); return mrl_io_error("io read failed"); }
            break;
        }
    }
    if (fclose(file) != 0) { free(bytes); return mrl_io_error("io read close failed"); }
    MrlIoStringResult result = mrl_io_copy(bytes, length);
    free(bytes);
    return result;
}

static bool mrl_io_write_utf8(const char *path, const char *text, const char **error) {
    static const char *success = NULL;
    if (error) *error = success;
    if (!path || !*path) { if (error) *error = "io write path is empty"; return false; }
    if (!text) { if (error) *error = "io write text is null"; return false; }
    size_t length = 0;
    while (length <= MRL_IO_MAX_BYTES && text[length]) ++length;
    if (length > MRL_IO_MAX_BYTES) { if (error) *error = "io input too large"; return false; }
    size_t path_length = strlen(path);
    if (path_length > MRL_IO_MAX_BYTES) { if (error) *error = "io write path is too long"; return false; }
    if (!mrl_io_validate((const unsigned char *)text, length, error) || !mrl_io_validate((const unsigned char *)path, path_length, error)) return false;
    char *temporary = NULL;
    FILE *file = mrl_io_open_temp(path, &temporary);
    if (!file) { if (error) *error = "io write temporary open failed"; return false; }
    bool ok = length == 0 || fwrite(text, 1, length, file) == length;
    if (ok && !mrl_io_sync(file)) ok = false;
    if (fclose(file) != 0) ok = false;
    if (!ok) { mrl_io_remove(temporary); free(temporary); if (error) *error = "io write failed"; return false; }
    if (!mrl_io_replace(temporary, path)) { mrl_io_remove(temporary); free(temporary); if (error) *error = "io write replace failed"; return false; }
    free(temporary);
    return ok;
}

#endif
