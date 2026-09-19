#include <stdlib.h>

typedef unsigned char _jBool;
typedef int i32;
typedef float f32;
typedef double f64;
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

#define M_PI 3.141

i32 add_i32_i32(i32 a, i32 b) {
    return a + b;
}

f32 add_f32_f32(f32 a, f32 b) {
    return a + b;
}

i32 add_i32_i32_i32(i32 a, i32 b, i32 c) {
    return a + b + c;
}

void jaguar_init() {
    string * e;
    i32 a;
    a = 10;
    e = string_from_cstr("hello");
    _jBool b = 1;
    string_destr(e);
    free(e);
}

f32 physics_compute_f32(f32 x) {
    return x * x;
}

f64 physics_compute_f64(f64 x) {
    return x * x;
}

f32 physics_common_GetCommon() {
    return 0;
}

typedef struct {
    f32 x;
    f32 y;
    _jBool normalized;
} vector2_t;

f32 make_speed(f32 v) {
    return v;
}

typedef struct MyClass MyClass;
typedef struct MyClass_vtable MyClass_vtable;
struct MyClass {
    MyClass_vtable *_vptr;
};
struct MyClass_vtable {
    void (*foo)(void *self);
};
void MyClass_foo(MyClass *self);
void MyClass_printff(MyClass *self);
void MyClass_destr(MyClass *self);
MyClass *MyClass_new(void);
MyClass *MyClass_ctor();
static MyClass_vtable MyClass_vtable_instance = {
    (void (*)(void *))MyClass_foo,
};
void MyClass_foo(MyClass *self) {
    _j_sys_print_string(string_from_cstr("foo from MyClass"));
    MyClass_printff(self);
}
void MyClass_printff(MyClass *self) {
    const i32 a = 1;
    _j_sys_print_string(string_from_cstr("bonjour"));
}
MyClass *MyClass_ctor() {
    MyClass *self = (MyClass*)calloc(1, sizeof(MyClass));
    if (!self) return 0;
    self->_vptr = &MyClass_vtable_instance;
    _j_sys_print_string(string_from_cstr("hello from class"));
    return self;
}
void MyClass_destr(MyClass *self) {
    _j_sys_print_string(string_from_cstr("bye from class"));
}

int main(int argc, char *argv[]) {
    string *param = string_from_cstr((argc > 1) ? argv[1] : "");
    MyClass * h = MyClass_ctor();
    h->_vptr->foo((void*)h);
    MyClass_destr(h);
    free(h);
    return 0;
}
