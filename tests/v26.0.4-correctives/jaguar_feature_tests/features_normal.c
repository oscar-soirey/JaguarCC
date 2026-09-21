#include <stdint.h>

#include <stdlib.h>

#include <string.h>

#include <stdio.h>

static void *_j_alloc_value(size_t size, const void *src) { void *p = malloc(size); if (!p) { fprintf(stderr, "Jaguar runtime error: allocation failed\n"); abort(); } memcpy(p, src, size); return p; }

typedef struct Fixed Fixed;

typedef enum TestEnum {
    TestEnum_A = 1,
    TestEnum_B = 7,
    TestEnum_C,
    TestEnum_D = TestEnum_B + 10
} TestEnum;

typedef unsigned char _jBool;
typedef int i32;
typedef struct _jString { size_t length; unsigned char literal; char data[]; } string;

/* Jaguar system library runtime (generated automatically). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

static string *string_alloc(size_t length) {
    string *s = (string *)malloc(sizeof(string) + length + 1);
    if (!s) return 0;
    s->length = length;
    s->data[length] = '\0';
    return s;
}
static string *string_from_cstr(const char *src) {
    string *s; size_t length;
    if (!src) src = "";
    length = strlen(src);
    s = string_alloc(length);
    if (!s) return 0;
    memcpy(s->data, src, length);
    s->literal = 0;
    return s;
}
typedef struct _jLiteralNode { string *s; struct _jLiteralNode *next; } _jLiteralNode;
static _jLiteralNode *_j_literal_head = 0;
static int _j_literal_atexit = 0;
static int _j_untrack_literal(string *self) { _jLiteralNode **pp; _jLiteralNode *n; if(!self)return 0; pp=&_j_literal_head; while(*pp){if((*pp)->s==self){n=*pp;*pp=n->next;free(n);return 1;}pp=&(*pp)->next;}return 0; }
static void _j_free_literals(void) { _jLiteralNode *n; _jLiteralNode *next; n=_j_literal_head; while(n){next=n->next;free(n->s);free(n);n=next;} _j_literal_head=0; }
static string *string_from_literal(const char *src) { string *s; _jLiteralNode *n; s=string_from_cstr(src); if(!s)return 0; s->literal=1; n=(_jLiteralNode*)malloc(sizeof(_jLiteralNode)); if(!n){free(s);return 0;} n->s=s;n->next=_j_literal_head;_j_literal_head=n; if(!_j_literal_atexit){atexit(_j_free_literals);_j_literal_atexit=1;} return s; }
static string *string_ctor(void) { return string_from_cstr(""); }
static void string_destr(string *self) {
    _jLiteralNode **pp; _jLiteralNode *n;
    if (!self) return;
    if (self->literal) {
        pp = &_j_literal_head;
        while (*pp) {
            if ((*pp)->s == self) {
                n = *pp; *pp = n->next; free(n); self->literal = 0; free(self); return;
            }
            pp = &(*pp)->next;
        }
        return;
    }
    free(self);
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
    string *out = string_alloc(a + b);
    if (!out) return 0;
    if (a) memcpy(out->data, self->data, a);
    if (b) memcpy(out->data + a, other->data, b);
    out->data[out->length] = '\0';
    return out;
}
static string *string_substring(string *self, i32 start, i32 length) {
    size_t a, n; string *out;
    if (!self || start < 0 || length < 0 || (size_t)start > self->length) return string_from_cstr("");
    a = (size_t)start; n = (size_t)length; if (n > self->length - a) n = self->length - a;
    out = string_alloc(n); if (!out) return 0;
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



struct Fixed {
    uint8_t bytes[4];
    float values[2];
};
static Fixed _j_struct_Fixed_default(void) { Fixed value; memset(&value, 0, sizeof(value)); return value; }
static Fixed *_j_struct_Fixed_new(void) { Fixed *value = (Fixed*)calloc(1, sizeof(Fixed)); if (!value) abort(); return value; }

void j_variadic(int8_t * fmt, ...);

void j_fixed(Fixed * value);

int main(void) {
    Fixed x;
    x.bytes[0] = TestEnum_A;
    x.bytes[1] = TestEnum_D;
    x.values[0] = 1.5;
    j_fixed((&x));
    j_variadic(((int8_t*)("x=%d")), TestEnum_A, TestEnum_D);
    return 0;
}
