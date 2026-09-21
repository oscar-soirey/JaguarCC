#include "jaguar_runtime.h"

typedef struct A A;

int32_t exe_var;

struct A {
    int32_t a;
};

int main(void) {
    _jList l;
    _j_list_init(&l,sizeof(int32_t),"i32");
    int32_t _jct0 = 1;
    _j_list_push(&l, &_jct0);
    int32_t _jct1 = 2;
    _j_list_push(&l, &_jct1);
    int32_t _jct2 = 3;
    _j_list_push(&l, &_jct2);
    int32_t _jct3 = 4;
    _j_list_push(&l, &_jct3);
    int32_t _jct4 = 5;
    _j_list_push(&l, &_jct4);
    _j_sys_print_i32((*(int32_t*)_j_list_get(&l,(size_t)(3))));
    _jContainer f;
    { float *_jtmp=( float*)malloc(sizeof(float)); if(!_jtmp)abort(); *_jtmp=5.0; _j_container_init(&f,_jtmp,"f32",0); }
    _j_sys_print_f32((*((float*)_j_container_get(&f))));
    _j_container_destroy(&f);
    _j_list_destroy(&l,0);
    return 0;
}
