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

typedef struct _jReflectEntry { const char *name; void *ptr; const char *type_name; } _jReflectEntry;
typedef struct _jReflectMap { _jReflectEntry *entries; size_t count; } _jReflectMap;
typedef struct _jReflectVTable { const char *type_name; _jReflectEntry *(*get_member)(void*, const char*); } _jReflectVTable;
static _jReflectEntry *_j_reflect_find(void *obj, const char *name) { _jReflectVTable *vt; if (!obj || !name) return 0; vt=*(_jReflectVTable**)obj; return (vt&&vt->get_member)?vt->get_member(obj,name):0; }
static void *_j_reflect_get_member(void *obj, const char *name) { _jReflectEntry *e=_j_reflect_find(obj,name); if(!e){fprintf(stderr,"Jaguar runtime error: member '%s' does not exist or is not exposed\n",name?name:"<null>"); return 0;} return e->ptr; }
static const char *_j_reflect_get_type(void *obj, const char *name) { _jReflectEntry *e=_j_reflect_find(obj,name); return e?e->type_name:0; }
static _jBool _j_reflect_member_exists(void *obj,const char *name) { return _j_reflect_find(obj,name)!=0; }

static void _j_reflect_set_member(void *obj,const char *name,const char *src_type,long long si,unsigned long long ui,double f,string *str,void *ptr) {
    _jReflectEntry *e=_j_reflect_find(obj,name); if(!e||!e->ptr||!e->type_name||!src_type){fprintf(stderr,"Jaguar runtime error: member '%s' does not exist or is not exposed\n",name?name:"<null>");return;}
    if(!strcmp(e->type_name,"string")&&!strcmp(src_type,"string")){*(string**)e->ptr=str;return;}
    if(!strcmp(e->type_name,"i32")||!strcmp(e->type_name,"int")){*(int*)e->ptr=(int)(f && (!strcmp(src_type,"f32")||!strcmp(src_type,"f64")||!strcmp(src_type,"float")) ? f : si);return;}
    if(!strcmp(e->type_name,"u32")){*(unsigned int*)e->ptr=(unsigned int)ui;return;}
    if(!strcmp(e->type_name,"i64")){*(long long*)e->ptr=(long long)si;return;}
    if(!strcmp(e->type_name,"u64")){*(unsigned long long*)e->ptr=(unsigned long long)ui;return;}
    if(!strcmp(e->type_name,"f32")||!strcmp(e->type_name,"float")){*(float*)e->ptr=(float)f;return;}
    if(!strcmp(e->type_name,"f64")){*(double*)e->ptr=f;return;}
    if(!strcmp(e->type_name,"bool")){*(unsigned char*)e->ptr=(unsigned char)si;return;}
    fprintf(stderr,"Jaguar runtime error: cannot assign value of type '%s' to reflected member '%s' of type '%s'\n",src_type,name?name:"<null>",e->type_name);
}

static void *_j_factory_construct(string *name);

static _jBool _j_reflect_member_exists(void *obj, const char *name);

static void _j_reflect_set_member(void *obj, const char *name, const char *type_name, long long si, unsigned long long ui, double f, string *str, void *ptr);

static void _j_reflect_print(void *obj, const char *name);

typedef struct MyClass MyClass;
typedef struct MyClass_vtable MyClass_vtable;
struct MyClass {
    MyClass_vtable *_vptr;
    _jReflectMap _reflect_map;
    i32 value;
};
struct MyClass_vtable {
    const char *type_name;
    _jReflectEntry *(*get_member)(void *self, const char *name);
};
static _jReflectEntry *MyClass_get_member(void *obj, const char *name) {
    MyClass *self = (MyClass*)obj;
    size_t i;
    if (!self->_reflect_map.entries) return 0;
    for (i = 0; i < self->_reflect_map.count; ++i)
        if (strcmp(self->_reflect_map.entries[i].name, name) == 0) return &self->_reflect_map.entries[i];
    return 0;
}
void MyClass_destr(MyClass *self);
MyClass *MyClass_new(void);
MyClass *MyClass_ctor();
static MyClass_vtable MyClass_vtable_instance = {
    "MyClass",
    MyClass_get_member,
};
MyClass *MyClass_ctor() {
    MyClass *self = (MyClass*)calloc(1, sizeof(MyClass));
    if (!self) return 0;
    self->_vptr = &MyClass_vtable_instance;
    self->_reflect_map.count = 1;
    self->_reflect_map.entries = (_jReflectEntry*)calloc(1, sizeof(_jReflectEntry));
    if (!self->_reflect_map.entries) { free(self); return 0; }
    self->_reflect_map.entries[0].name = "value";
    self->_reflect_map.entries[0].ptr = (void*)&self->value;
    self->_reflect_map.entries[0].type_name = "i32";
    self->value = 10;
    _j_sys_print_string(string_from_cstr("hello from class"));
    return self;
}
void MyClass_destr(MyClass *self) {
    _j_sys_print_string(string_from_cstr("bye from class"));
}

int main(int argc, char *argv[]) {
    string *param = string_from_cstr((argc > 1) ? argv[1] : "");
    MyClass * h = (MyClass*)_j_factory_construct(string_from_cstr("MyClass"));
    _j_reflect_set_member((void*)h,param->data,"i32",(long long)(43),(unsigned long long)(43),0.0,0,0);
    _j_sys_print_i32(h->value);
    if (h) MyClass_destr(h);
    free(h);
    return 0;
}

/* Jaguar native dynamic reflection / factory runtime. */
#include <string.h>
static void _j_reflect_print(void *obj,const char *name) {
    _jReflectEntry *e=_j_reflect_find(obj,name); if(!e){printf("<null>\n");return;}
    if(!strcmp(e->type_name,"string")){string *s=*(string**)e->ptr;printf("%s\n",(s&&s->data)?s->data:"");}
    else if(!strcmp(e->type_name,"bool")){printf("%s\n",*(unsigned char*)e->ptr?"true":"false");}
    else if(!strcmp(e->type_name,"i32")||!strcmp(e->type_name,"int")){printf("%d\n",*(int*)e->ptr);}
    else if(!strcmp(e->type_name,"u32")){printf("%u\n",*(unsigned int*)e->ptr);}
    else if(!strcmp(e->type_name,"i64")){printf("%lld\n",*(long long*)e->ptr);}
    else if(!strcmp(e->type_name,"u64")){printf("%llu\n",*(unsigned long long*)e->ptr);}
    else if(!strcmp(e->type_name,"f32")||!strcmp(e->type_name,"float")){printf("%g\n",(double)*(float*)e->ptr);}
    else if(!strcmp(e->type_name,"f64")){printf("%g\n",*(double*)e->ptr);}
    else printf("<object:%s>\n",e->type_name);
}
static void *_j_factory_construct(string *name) {
    if(!name||!name->data) {
        fprintf(stderr, "Jaguar runtime error: factory:construct() received a null class name\n");
        abort();
    }
    if(strcmp(name->data,"MyClass")==0)return(void*)MyClass_ctor();
    fprintf(stderr, "Jaguar runtime error: cannot construct class '%s': class is not registered\n", name->data);
    abort();
    return 0;
}
