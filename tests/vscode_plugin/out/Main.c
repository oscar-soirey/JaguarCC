#include <stdlib.h>

typedef unsigned char _jBool;
typedef int i32;
typedef struct _jString string;
struct _jString { char *data; size_t length; };

/* Jaguar system library runtime (generated automatically). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

static string *string_from_cstr(const char *src) {
    string *s = (string *)calloc(1, sizeof(string));
    if (!s) return 0;
    if (!src) src = "";
    s->length = strlen(src);
    s->data = (char *)malloc(s->length + 1);
    if (!s->data) { free(s); return 0; }
    memcpy(s->data, src, s->length + 1);
    return s;
}

static string *string_ctor(void) { return string_from_cstr(""); }
static void string_destr(string *self) {
    if (!self) return;
    free(self->data);
    self->data = 0;
    self->length = 0;
}
static i32 string_length(string *self) { return self ? (i32)self->length : 0; }
static _jBool string_empty(string *self) { return (!self || self->length == 0) ? 1 : 0; }
static _jBool string_equals(string *self, string *other) {
    if (!self || !other) return self == other;
    return strcmp(self->data ? self->data : "", other->data ? other->data : "") == 0;
}
static _jBool string_contains(string *self, string *needle) {
    if (!self || !needle) return 0;
    return strstr(self->data ? self->data : "", needle->data ? needle->data : "") != 0;
}
static _jBool string_starts_with(string *self, string *prefix) {
    if (!self || !prefix || prefix->length > self->length) return 0;
    return memcmp(self->data, prefix->data, prefix->length) == 0;
}
static _jBool string_ends_with(string *self, string *suffix) {
    if (!self || !suffix || suffix->length > self->length) return 0;
    return memcmp(self->data + self->length - suffix->length, suffix->data, suffix->length) == 0;
}
static string *string_concat(string *self, string *other) {
    size_t a = self ? self->length : 0, b = other ? other->length : 0;
    string *out = (string *)calloc(1, sizeof(string));
    if (!out) return 0;
    out->length = a + b; out->data = (char *)malloc(out->length + 1);
    if (!out->data) { free(out); return 0; }
    if (a) memcpy(out->data, self->data, a);
    if (b) memcpy(out->data + a, other->data, b);
    out->data[out->length] = '\0';
    return out;
}
static string *string_substring(string *self, i32 start, i32 length) {
    size_t a, n; string *out;
    if (!self || start < 0 || length < 0 || (size_t)start > self->length) return string_from_cstr("");
    a = (size_t)start; n = (size_t)length; if (n > self->length - a) n = self->length - a;
    out = (string *)calloc(1, sizeof(string)); if (!out) return 0;
    out->length = n; out->data = (char *)malloc(n + 1); if (!out->data) { free(out); return 0; }
    memcpy(out->data, self->data + a, n); out->data[n] = '\0'; return out;
}
static i32 string_char_at(string *self, i32 index) {
    if (!self || index < 0 || (size_t)index >= self->length) return -1;
    return (unsigned char)self->data[index];
}
static string *string_transform_case(string *self, int upper) {
    size_t i; string *out;
    out = string_from_cstr(self ? self->data : ""); if (!out) return 0;
    for (i = 0; i < out->length; ++i) {
        unsigned char c = (unsigned char)out->data[i];
        if (upper && c >= 'a' && c <= 'z') out->data[i] = (char)(c - 'a' + 'A');
        if (!upper && c >= 'A' && c <= 'Z') out->data[i] = (char)(c - 'A' + 'a');
    } return out;
}
static string *string_to_upper(string *self) { return string_transform_case(self, 1); }
static string *string_to_lower(string *self) { return string_transform_case(self, 0); }

static void _j_sys_print_string(string *s) {
    printf("%s\n", (s && s->data) ? s->data : "");
}

static void _j_sys_print_int(int v) {
    printf("%d\n", v);
}

static void _j_sys_print_i8(signed char v) {
    printf("%d\n", (int)v);
}

static void _j_sys_print_u8(unsigned char v) {
    printf("%u\n", (unsigned int)v);
}

static void _j_sys_print_i16(short v) {
    printf("%d\n", (int)v);
}

static void _j_sys_print_u16(unsigned short v) {
    printf("%u\n", (unsigned int)v);
}

static void _j_sys_print_i32(int v) {
    printf("%d\n", v);
}

static void _j_sys_print_u32(unsigned int v) {
    printf("%u\n", v);
}

static void _j_sys_print_i64(long long v) {
    printf("%lld\n", v);
}

static void _j_sys_print_u64(unsigned long long v) {
    printf("%llu\n", v);
}

static void _j_sys_print_float(float v) {
    printf("%g\n", (double)v);
}

static void _j_sys_print_f32(float v) {
    printf("%g\n", (double)v);
}

static void _j_sys_print_f64(double v) {
    printf("%g\n", v);
}

static void _j_sys_print_bool(_jBool v) {
    printf("%s\n", v ? "true" : "false");
}

static void _j_sys_print_dynamic(void *data, const char *type) {
    if (!data || !type) { printf("<null>\n"); return; }
    if (!strcmp(type, "string")) { string *v=(string*)data; printf("%s\n", (v && v->data) ? v->data : ""); return; }
    if (!strcmp(type, "bool")) { printf("%s\n", *((_jBool*)data) ? "true" : "false"); return; }
    if (!strcmp(type, "f32") || !strcmp(type, "float")) { printf("%g\n", (double)*((float*)data)); return; }
    if (!strcmp(type, "f64")) { printf("%g\n", *((double*)data)); return; }
    if (!strcmp(type, "i8")) { printf("%d\n", (int)*((signed char*)data)); return; }
    if (!strcmp(type, "u8")) { printf("%u\n", (unsigned int)*((unsigned char*)data)); return; }
    if (!strcmp(type, "i16")) { printf("%d\n", (int)*((short*)data)); return; }
    if (!strcmp(type, "u16")) { printf("%u\n", (unsigned int)*((unsigned short*)data)); return; }
    if (!strcmp(type, "i32") || !strcmp(type, "int")) { printf("%d\n", *((int*)data)); return; }
    if (!strcmp(type, "u32")) { printf("%u\n", *((unsigned int*)data)); return; }
    if (!strcmp(type, "i64")) { printf("%lld\n", *((long long*)data)); return; }
    if (!strcmp(type, "u64")) { printf("%llu\n", *((unsigned long long*)data)); return; }
    fprintf(stderr, "Jaguar runtime error: impossible d'imprimer une valeur dynamic_list de type '%s'\n", type);
    abort();
}

i32 math_add(i32 a, i32 b) {
    _j_sys_print_i32(a);
    _j_sys_print_i32(b);
    return a + b;
}

int main(void) {
    string * a;
    _j_sys_print_i32(math_add(4, 10));
    if (a) string_destr(a);
    free(a);
    return 0;
}
