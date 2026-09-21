#ifndef JAGUAR_RUNTIME_H

#define JAGUAR_RUNTIME_H

#include <stddef.h>

#include <stdio.h>

#include <stdlib.h>

#include <string.h>

#include <stdint.h>

typedef unsigned char _jBool;

typedef int i32;

typedef float f32;

typedef struct _jString { size_t length; char data[]; } string;

typedef struct _jDynamicItem { void *data; size_t size; const char *type; void (*destroy)(void*); } _jDynamicItem;

typedef struct _jDynamicList { _jDynamicItem *items; size_t size; size_t cap; } _jDynamicList;

typedef struct _jList { void **items; size_t size; size_t cap; size_t elem_size; const char *elem_type; } _jList;

typedef struct _jMapEntry { void *key; void *value; } _jMapEntry;

typedef struct _jMap { _jMapEntry *items; size_t size; size_t cap; size_t key_size; size_t value_size; const char *key_type; const char *value_type; } _jMap;

typedef struct _jContainer { void *data; const char *type; void (*destroy)(void*); } _jContainer;

void *_j_alloc_value(size_t size, const void *src);

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

void *_j_memdup(const void *src,size_t n);

void _j_destroy_string_value(void*p);

void _j_dynamic_list_init(_jDynamicList*l);

void _j_dynamic_list_grow(_jDynamicList*l);

void _j_dynamic_list_push_copy(_jDynamicList*l,const void*v,size_t n,const char*t);

void _j_dynamic_list_push_owned(_jDynamicList*l,void*v,const char*t,void(*destroy)(void*));

void _j_dynamic_list_push_borrowed(_jDynamicList*l,void*v,const char*t);

void *_j_dynamic_list_get(_jDynamicList*l,size_t i);

const char *_j_dynamic_list_type(_jDynamicList*l,size_t i);

void _j_dynamic_list_destroy(_jDynamicList*l);

void _j_list_init(_jList*l,size_t es,const char*t);

void _j_destroy_string_slot(void*p);

void _j_list_push(_jList*l,const void*v);

void *_j_list_get(_jList*l,size_t i);

void _j_list_destroy(_jList*l,void(*destroy)(void*));

void _j_map_init(_jMap*m,size_t ks,size_t vs,const char*kt,const char*vt);

int _j_map_keyeq(const void*a,const void*b,size_t n,const char*t);

void *_j_map_get(_jMap*m,const void*k);

void *_j_map_get_string(_jMap*m,string*k);

void _j_map_emplace(_jMap*m,const void*k,const void*v);

void _j_map_destroy(_jMap*m,void(*kd)(void*),void(*vd)(void*));

void _j_container_init(_jContainer*c,void*d,const char*t,void(*destroy)(void*));

void *_j_container_get(_jContainer*c);

void _j_container_destroy(_jContainer*c);

#endif
