#include "jaguar_runtime.h"

typedef int32_t (*fptr)(int32_t, int32_t);



int32_t add(int32_t a, int32_t b) {
    return a + b;
}

int32_t multiply(int32_t a, int32_t b) {
    return a * b;
}

int main(int argc, char *argv[]) {
    string *args = string_from_cstr((argc > 1) ? argv[1] : "");
    int32_t (*f)(int32_t, int32_t) = add;
    int32_t r = f(1, 2);
    _j_sys_print_i32(r);
    f = multiply;
    int32_t r2 = f(4, 5);
    _j_sys_print_i32(r2);
    return 0;
}
