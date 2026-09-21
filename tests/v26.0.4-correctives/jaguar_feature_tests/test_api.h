#ifdef __cplusplus
extern "C" {
#endif

typedef enum TestEnumC {
    C_A = 1,
    C_B = 7,
    C_C,
    C_D = C_B + 10
} TestEnumC;

typedef struct FixedC {
    unsigned char bytes[4];
    float values[2];
} FixedC;

void c_variadic(const char* fmt, ...);

typedef void (*CVariadicFn)(const char* fmt, ...);

#ifdef __cplusplus
}
#endif
