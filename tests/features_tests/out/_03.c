#include "jaguar_runtime.h"

typedef struct math_Vec2 math_Vec2;
typedef union math_Value math_Value;

struct math_Vec2 {
    float x;
    float y;
};
static math_Vec2 _j_struct_math_Vec2_default(void) { math_Vec2 value; memset(&value, 0, sizeof(value)); return value; }
static math_Vec2 *_j_struct_math_Vec2_new(void) { math_Vec2 *value = (math_Vec2*)calloc(1, sizeof(math_Vec2)); if (!value) abort(); return value; }

union math_Value {
    int32_t i;
    float f;
};
union math_Value _j_union_math_Value;

int32_t math_global = 10;

int32_t math_add(int32_t a, int32_t b) {
    return a + b;
}

int main(void) {
    math_Vec2 v = _j_struct_math_Vec2_default();
    v.x = 3.0;
    v.y = 4.0;
    math_Value value;
    value.i = 123;
    _j_sys_print_i32((int32_t)v.x);
    _j_sys_print_i32(value.i);
    _j_sys_print_i32(math_global);
    _j_sys_print_i32(math_add(10, 20));
    return 0;
}
