#include "jaguar_runtime.h"

void *_j_alloc_value(size_t size, const void *src) { void *p = malloc(size); if (!p) { fprintf(stderr, "Jaguar runtime error: allocation failed\n"); abort(); } memcpy(p, src, size); return p; }

/* Jaguar system library runtime (generated automatically). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

string *string_alloc(size_t length) {
    string *s = (string *)malloc(sizeof(string) + length + 1);
    if (!s) return 0;
    s->length = length;
    s->data[length] = '\0';
    return s;
}
string *string_from_cstr(const char *src) {
    string *s; size_t length;
    if (!src) src = "";
    length = strlen(src);
    s = string_alloc(length);
    if (!s) return 0;
    memcpy(s->data, src, length);
    return s;
}
string *string_ctor(void) { return string_from_cstr(""); }
void string_destr(string *self) {
    if (!self) return;
    free(self);
}
i32 string_length(string *self) { return self ? (i32)self->length : 0; }
_jBool string_empty(string *self) { return (!self || self->length == 0) ? 1 : 0; }
_jBool string_equals(string *self, string *other) {
    if (!self || !other) return self == other;
    return strcmp(self->data ? self->data : "", other->data ? other->data : "") == 0;
}

_jBool string_contains(string *self, string *needle) {
    if (!self || !needle) return 0;
    return strstr(self->data ? self->data : "", needle->data ? needle->data : "") != 0;
}
_jBool string_starts_with(string *self, string *prefix) {
    if (!self || !prefix || prefix->length > self->length) return 0;
    return memcmp(self->data, prefix->data, prefix->length) == 0;
}
_jBool string_ends_with(string *self, string *suffix) {
    if (!self || !suffix || suffix->length > self->length) return 0;
    return memcmp(self->data + self->length - suffix->length, suffix->data, suffix->length) == 0;
}
string *string_concat(string *self, string *other) {
    size_t a = self ? self->length : 0, b = other ? other->length : 0;
    string *out = string_alloc(a + b);
    if (!out) return 0;
    if (a) memcpy(out->data, self->data, a);
    if (b) memcpy(out->data + a, other->data, b);
    out->data[out->length] = '\0';
    return out;
}
string *string_substring(string *self, i32 start, i32 length) {
    size_t a, n; string *out;
    if (!self || start < 0 || length < 0 || (size_t)start > self->length) return string_from_cstr("");
    a = (size_t)start; n = (size_t)length; if (n > self->length - a) n = self->length - a;
    out = string_alloc(n); if (!out) return 0;
    memcpy(out->data, self->data + a, n); out->data[n] = '\0'; return out;
}
i32 string_char_at(string *self, i32 index) {
    if (!self || index < 0 || (size_t)index >= self->length) return -1;
    return (unsigned char)self->data[index];
}
string *string_transform_case(string *self, int upper) {
    size_t i; string *out;
    out = string_from_cstr(self ? self->data : ""); if (!out) return 0;
    for (i = 0; i < out->length; ++i) {
        unsigned char c = (unsigned char)out->data[i];
        if (upper && c >= 'a' && c <= 'z') out->data[i] = (char)(c - 'a' + 'A');
        if (!upper && c >= 'A' && c <= 'Z') out->data[i] = (char)(c - 'A' + 'a');
    } return out;
}
string *string_to_upper(string *self) { return string_transform_case(self, 1); }
string *string_to_lower(string *self) { return string_transform_case(self, 0); }

void _j_sys_print_string(string *s) {
    printf("%s\n", (s && s->data) ? s->data : "");
}

void _j_sys_print_int(int v) {
    printf("%d\n", v);
}

void _j_sys_print_i8(signed char v) {
    printf("%d\n", (int)v);
}

void _j_sys_print_u8(unsigned char v) {
    printf("%u\n", (unsigned int)v);
}

void _j_sys_print_i16(short v) {
    printf("%d\n", (int)v);
}

void _j_sys_print_u16(unsigned short v) {
    printf("%u\n", (unsigned int)v);
}

void _j_sys_print_i32(int v) {
    printf("%d\n", v);
}

void _j_sys_print_u32(unsigned int v) {
    printf("%u\n", v);
}

void _j_sys_print_i64(long long v) {
    printf("%lld\n", v);
}

void _j_sys_print_u64(unsigned long long v) {
    printf("%llu\n", v);
}

void _j_sys_print_float(float v) {
    printf("%g\n", (double)v);
}

void _j_sys_print_f32(float v) {
    printf("%g\n", (double)v);
}

void _j_sys_print_f64(double v) {
    printf("%g\n", v);
}

void _j_sys_print_bool(_jBool v) {
    printf("%s\n", v ? "true" : "false");
}

void _j_sys_print_dynamic(void *data, const char *type) {
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
    fprintf(stderr, "Jaguar runtime error: cannot print a dynamic_list value of type '%s'\n", type);
    abort();
}

/* Jaguar containers: runtime polymorphic storage, no C templates. */
#include <string.h>
void *_j_memdup(const void *src,size_t n){void*p=malloc(n);if(p&&src)memcpy(p,src,n);return p;}
void _j_destroy_string_value(void*p){if(p){string_destr((string*)p);}}
void _j_dynamic_list_init(_jDynamicList*l){l->items=0;l->size=0;l->cap=0;}
void _j_dynamic_list_grow(_jDynamicList*l){if(l->size==l->cap){size_t nc=l->cap?l->cap*2:4;_jDynamicItem*ni=(_jDynamicItem*)realloc(l->items,nc*sizeof(_jDynamicItem));if(!ni)abort();l->items=ni;l->cap=nc;}}
void _j_dynamic_list_push_copy(_jDynamicList*l,const void*v,size_t n,const char*t){_j_dynamic_list_grow(l);l->items[l->size].data=_j_memdup(v,n);if(!l->items[l->size].data)abort();l->items[l->size].size=n;l->items[l->size].type=t;l->items[l->size].destroy=0;l->size++;}
void _j_dynamic_list_push_owned(_jDynamicList*l,void*v,const char*t,void(*destroy)(void*)){_j_dynamic_list_grow(l);l->items[l->size].data=v;l->items[l->size].size=sizeof(void*);l->items[l->size].type=t;l->items[l->size].destroy=destroy;l->size++;}
void _j_dynamic_list_push_borrowed(_jDynamicList*l,void*v,const char*t){_j_dynamic_list_push_owned(l,v,t,0);}
void *_j_dynamic_list_get(_jDynamicList*l,size_t i){if(!l||i>=l->size){fprintf(stderr,"Jaguar runtime error: dynamic_list index %lu out of range\n",(unsigned long)i);abort();}return l->items[i].data;}
const char *_j_dynamic_list_type(_jDynamicList*l,size_t i){if(!l||i>=l->size){fprintf(stderr,"Jaguar runtime error: dynamic_list index %lu out of range\n",(unsigned long)i);abort();}return l->items[i].type;}
void _j_dynamic_list_destroy(_jDynamicList*l){size_t i;if(!l)return;for(i=0;i<l->size;i++)if(l->items[i].destroy)l->items[i].destroy(l->items[i].data);free(l->items);l->items=0;l->size=0;l->cap=0;}
void _j_list_init(_jList*l,size_t es,const char*t){l->items=0;l->size=0;l->cap=0;l->elem_size=es;l->elem_type=t;}
void _j_destroy_string_slot(void*p){string*s=p?*(string**)p:0;if(s){string_destr(s);}}
void _j_list_push(_jList*l,const void*v){void*p;if(l->size==l->cap){size_t nc=l->cap?l->cap*2:4;void**ni=(void**)realloc(l->items,nc*sizeof(void*));if(!ni)abort();l->items=ni;l->cap=nc;}p=_j_memdup(v,l->elem_size);if(!p)abort();l->items[l->size++]=p;}
void *_j_list_get(_jList*l,size_t i){if(!l||i>=l->size){fprintf(stderr,"Jaguar runtime error: list index %lu out of range\n",(unsigned long)i);abort();}return l->items[i];}
void _j_list_destroy(_jList*l,void(*destroy)(void*)){size_t i;if(!l)return;for(i=0;i<l->size;i++){if(destroy)destroy(l->items[i]);free(l->items[i]);}free(l->items);l->items=0;l->size=0;l->cap=0;}
void _j_map_init(_jMap*m,size_t ks,size_t vs,const char*kt,const char*vt){m->items=0;m->size=0;m->cap=0;m->key_size=ks;m->value_size=vs;m->key_type=kt;m->value_type=vt;}
int _j_map_keyeq(const void*a,const void*b,size_t n,const char*t){if(!strcmp(t,"string")){string*sa=*(string**)a;string*sb=*(string**)b;return sa&&sb&&sa->data&&sb->data&&!strcmp(sa->data,sb->data);}return memcmp(a,b,n)==0;}
void *_j_map_get(_jMap*m,const void*k){size_t i;for(i=0;i<m->size;i++)if(_j_map_keyeq(m->items[i].key,k,m->key_size,m->key_type))return m->items[i].value;return 0;}
void *_j_map_get_string(_jMap*m,string*k){size_t i;for(i=0;i<m->size;i++){string*sk=*(string**)m->items[i].key;if(sk&&k&&sk->data&&k->data&&!strcmp(sk->data,k->data))return m->items[i].value;}fprintf(stderr,"Jaguar runtime error: map key not found\n");abort();return 0;}
void _j_map_emplace(_jMap*m,const void*k,const void*v){size_t i;void*kp;void*vp;for(i=0;i<m->size;i++)if(_j_map_keyeq(m->items[i].key,k,m->key_size,m->key_type)){memcpy(m->items[i].value,v,m->value_size);return;}if(m->size==m->cap){size_t nc=m->cap?m->cap*2:4;_jMapEntry*ni=(_jMapEntry*)realloc(m->items,nc*sizeof(_jMapEntry));if(!ni)abort();m->items=ni;m->cap=nc;}kp=_j_memdup(k,m->key_size);vp=_j_memdup(v,m->value_size);if(!kp||!vp)abort();m->items[m->size].key=kp;m->items[m->size].value=vp;m->size++;}
void _j_map_destroy(_jMap*m,void(*kd)(void*),void(*vd)(void*)){size_t i;if(!m)return;for(i=0;i<m->size;i++){if(kd)kd(m->items[i].key);if(vd)vd(m->items[i].value);free(m->items[i].key);free(m->items[i].value);}free(m->items);m->items=0;m->size=0;m->cap=0;}
void _j_container_init(_jContainer*c,void*d,const char*t,void(*destroy)(void*)){c->data=d;c->type=t;c->destroy=destroy;}
void *_j_container_get(_jContainer*c){if(!c||!c->data){fprintf(stderr,"Jaguar runtime error: empty container access\n");abort();}return c->data;}
void _j_container_destroy(_jContainer*c){if(!c)return;if(c->data){if(c->destroy)c->destroy(c->data);else free(c->data);}c->data=0;c->destroy=0;}
