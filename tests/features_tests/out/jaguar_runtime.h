#ifndef JAGUAR_RUNTIME_H

#define JAGUAR_RUNTIME_H

#include <stddef.h>

#include <stdio.h>

#include <stdlib.h>

#include <string.h>

#include <stdint.h>

typedef unsigned char _jBool;

typedef int i32;

typedef struct _jString { size_t length; char data[]; } string;

string *string_alloc(size_t length);

string *string_from_cstr(const char *src);

string *string_ctor(void);

void string_destr(string *self);

i32 string_length(string *self);

_jBool string_empty(string *self);

_jBool string_equals(string *self, string *other);

_jBool string_contains(string *self, string *needle);

_jBool string_starts_with(string *self, string *prefix);

_jBool string_ends_with(string *self, string *suffix);

string *string_concat(string *self, string *other);

string *string_substring(string *self, i32 start, i32 length);

i32 string_char_at(string *self, i32 index);

string *string_transform_case(string *self, int upper);

string *string_to_upper(string *self);

string *string_to_lower(string *self);

void _j_sys_print_string(string *s);

void _j_sys_print_int(int v);

void _j_sys_print_i8(signed char v);

void _j_sys_print_u8(unsigned char v);

void _j_sys_print_i16(short v);

void _j_sys_print_u16(unsigned short v);

void _j_sys_print_i32(int v);

void _j_sys_print_u32(unsigned int v);

void _j_sys_print_i64(long long v);

void _j_sys_print_u64(unsigned long long v);

void _j_sys_print_float(float v);

void _j_sys_print_f32(float v);

void _j_sys_print_f64(double v);

void _j_sys_print_bool(_jBool v);

void _j_sys_print_dynamic(void *data, const char *type);

#endif
