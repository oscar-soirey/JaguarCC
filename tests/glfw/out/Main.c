#include <stdint.h>

#include <stdlib.h>

#include <string.h>

#include <stdio.h>

static void *_j_alloc_value(size_t size, const void *src) { void *p = malloc(size); if (!p) { fprintf(stderr, "Jaguar runtime error: allocation failed\n"); abort(); } memcpy(p, src, size); return p; }

typedef struct GLFWallocator GLFWallocator;
typedef struct GLFWcursor GLFWcursor;
typedef struct GLFWgamepadstate GLFWgamepadstate;
typedef struct GLFWgammaramp GLFWgammaramp;
typedef struct GLFWimage GLFWimage;
typedef struct GLFWmonitor GLFWmonitor;
typedef struct GLFWvidmode GLFWvidmode;
typedef struct GLFWwindow GLFWwindow;

typedef unsigned char _jBool;
typedef unsigned char u8;
typedef int i32;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef float f32;
typedef double f64;
typedef struct _jString { size_t length; unsigned char literal; char data[]; } string;

typedef void (*GLFWglproc)(void);
typedef void (*GLFWvkproc)(void);
typedef void * (*GLFWallocatefun)(uint64_t, void *);
typedef void * (*GLFWreallocatefun)(void *, uint64_t, void *);
typedef void (*GLFWdeallocatefun)(void *, void *);
typedef void (*GLFWerrorfun)(int32_t, int8_t *);
typedef void (*GLFWwindowposfun)(GLFWwindow *, int32_t, int32_t);
typedef void (*GLFWwindowsizefun)(GLFWwindow *, int32_t, int32_t);
typedef void (*GLFWwindowclosefun)(GLFWwindow *);
typedef void (*GLFWwindowrefreshfun)(GLFWwindow *);
typedef void (*GLFWwindowfocusfun)(GLFWwindow *, int32_t);
typedef void (*GLFWwindowiconifyfun)(GLFWwindow *, int32_t);
typedef void (*GLFWwindowmaximizefun)(GLFWwindow *, int32_t);
typedef void (*GLFWframebuffersizefun)(GLFWwindow *, int32_t, int32_t);
typedef void (*GLFWwindowcontentscalefun)(GLFWwindow *, float, float);
typedef void (*GLFWmousebuttonfun)(GLFWwindow *, int32_t, int32_t, int32_t);
typedef void (*GLFWcursorposfun)(GLFWwindow *, double, double);
typedef void (*GLFWcursorenterfun)(GLFWwindow *, int32_t);
typedef void (*GLFWscrollfun)(GLFWwindow *, double, double);
typedef void (*GLFWkeyfun)(GLFWwindow *, int32_t, int32_t, int32_t, int32_t);
typedef void (*GLFWcharfun)(GLFWwindow *, uint32_t);
typedef void (*GLFWcharmodsfun)(GLFWwindow *, uint32_t, int32_t);
typedef void (*GLFWdropfun)(GLFWwindow *, int32_t, int8_t * *);
typedef void (*GLFWmonitorfun)(GLFWmonitor *, int32_t);
typedef void (*GLFWjoystickfun)(int32_t, int32_t);

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

#define GLFW_VERSION_MAJOR 3

#define GLFW_VERSION_MINOR 4

#define GLFW_VERSION_REVISION 0

#define GLFW_TRUE 1

#define GLFW_FALSE 0

#define GLFW_RELEASE 0

#define GLFW_PRESS 1

#define GLFW_REPEAT 2

#define GLFW_HAT_CENTERED 0

#define GLFW_HAT_UP 1

#define GLFW_HAT_RIGHT 2

#define GLFW_HAT_DOWN 4

#define GLFW_HAT_LEFT 8

#define GLFW_HAT_RIGHT_UP (GLFW_HAT_RIGHT | GLFW_HAT_UP)

#define GLFW_HAT_RIGHT_DOWN (GLFW_HAT_RIGHT | GLFW_HAT_DOWN)

#define GLFW_HAT_LEFT_UP (GLFW_HAT_LEFT  | GLFW_HAT_UP)

#define GLFW_HAT_LEFT_DOWN (GLFW_HAT_LEFT  | GLFW_HAT_DOWN)

#define GLFW_KEY_UNKNOWN -1

#define GLFW_KEY_SPACE 32

#define GLFW_KEY_APOSTROPHE 39

#define GLFW_KEY_COMMA 44

#define GLFW_KEY_MINUS 45

#define GLFW_KEY_PERIOD 46

#define GLFW_KEY_SLASH 47

#define GLFW_KEY_0 48

#define GLFW_KEY_1 49

#define GLFW_KEY_2 50

#define GLFW_KEY_3 51

#define GLFW_KEY_4 52

#define GLFW_KEY_5 53

#define GLFW_KEY_6 54

#define GLFW_KEY_7 55

#define GLFW_KEY_8 56

#define GLFW_KEY_9 57

#define GLFW_KEY_SEMICOLON 59

#define GLFW_KEY_EQUAL 61

#define GLFW_KEY_A 65

#define GLFW_KEY_B 66

#define GLFW_KEY_C 67

#define GLFW_KEY_D 68

#define GLFW_KEY_E 69

#define GLFW_KEY_F 70

#define GLFW_KEY_G 71

#define GLFW_KEY_H 72

#define GLFW_KEY_I 73

#define GLFW_KEY_J 74

#define GLFW_KEY_K 75

#define GLFW_KEY_L 76

#define GLFW_KEY_M 77

#define GLFW_KEY_N 78

#define GLFW_KEY_O 79

#define GLFW_KEY_P 80

#define GLFW_KEY_Q 81

#define GLFW_KEY_R 82

#define GLFW_KEY_S 83

#define GLFW_KEY_T 84

#define GLFW_KEY_U 85

#define GLFW_KEY_V 86

#define GLFW_KEY_W 87

#define GLFW_KEY_X 88

#define GLFW_KEY_Y 89

#define GLFW_KEY_Z 90

#define GLFW_KEY_LEFT_BRACKET 91

#define GLFW_KEY_BACKSLASH 92

#define GLFW_KEY_RIGHT_BRACKET 93

#define GLFW_KEY_GRAVE_ACCENT 96

#define GLFW_KEY_WORLD_1 161

#define GLFW_KEY_WORLD_2 162

#define GLFW_KEY_ESCAPE 256

#define GLFW_KEY_ENTER 257

#define GLFW_KEY_TAB 258

#define GLFW_KEY_BACKSPACE 259

#define GLFW_KEY_INSERT 260

#define GLFW_KEY_DELETE 261

#define GLFW_KEY_RIGHT 262

#define GLFW_KEY_LEFT 263

#define GLFW_KEY_DOWN 264

#define GLFW_KEY_UP 265

#define GLFW_KEY_PAGE_UP 266

#define GLFW_KEY_PAGE_DOWN 267

#define GLFW_KEY_HOME 268

#define GLFW_KEY_END 269

#define GLFW_KEY_CAPS_LOCK 280

#define GLFW_KEY_SCROLL_LOCK 281

#define GLFW_KEY_NUM_LOCK 282

#define GLFW_KEY_PRINT_SCREEN 283

#define GLFW_KEY_PAUSE 284

#define GLFW_KEY_F1 290

#define GLFW_KEY_F2 291

#define GLFW_KEY_F3 292

#define GLFW_KEY_F4 293

#define GLFW_KEY_F5 294

#define GLFW_KEY_F6 295

#define GLFW_KEY_F7 296

#define GLFW_KEY_F8 297

#define GLFW_KEY_F9 298

#define GLFW_KEY_F10 299

#define GLFW_KEY_F11 300

#define GLFW_KEY_F12 301

#define GLFW_KEY_F13 302

#define GLFW_KEY_F14 303

#define GLFW_KEY_F15 304

#define GLFW_KEY_F16 305

#define GLFW_KEY_F17 306

#define GLFW_KEY_F18 307

#define GLFW_KEY_F19 308

#define GLFW_KEY_F20 309

#define GLFW_KEY_F21 310

#define GLFW_KEY_F22 311

#define GLFW_KEY_F23 312

#define GLFW_KEY_F24 313

#define GLFW_KEY_F25 314

#define GLFW_KEY_KP_0 320

#define GLFW_KEY_KP_1 321

#define GLFW_KEY_KP_2 322

#define GLFW_KEY_KP_3 323

#define GLFW_KEY_KP_4 324

#define GLFW_KEY_KP_5 325

#define GLFW_KEY_KP_6 326

#define GLFW_KEY_KP_7 327

#define GLFW_KEY_KP_8 328

#define GLFW_KEY_KP_9 329

#define GLFW_KEY_KP_DECIMAL 330

#define GLFW_KEY_KP_DIVIDE 331

#define GLFW_KEY_KP_MULTIPLY 332

#define GLFW_KEY_KP_SUBTRACT 333

#define GLFW_KEY_KP_ADD 334

#define GLFW_KEY_KP_ENTER 335

#define GLFW_KEY_KP_EQUAL 336

#define GLFW_KEY_LEFT_SHIFT 340

#define GLFW_KEY_LEFT_CONTROL 341

#define GLFW_KEY_LEFT_ALT 342

#define GLFW_KEY_LEFT_SUPER 343

#define GLFW_KEY_RIGHT_SHIFT 344

#define GLFW_KEY_RIGHT_CONTROL 345

#define GLFW_KEY_RIGHT_ALT 346

#define GLFW_KEY_RIGHT_SUPER 347

#define GLFW_KEY_MENU 348

#define GLFW_KEY_LAST GLFW_KEY_MENU

#define GLFW_MOD_SHIFT 0x0001

#define GLFW_MOD_CONTROL 0x0002

#define GLFW_MOD_ALT 0x0004

#define GLFW_MOD_SUPER 0x0008

#define GLFW_MOD_CAPS_LOCK 0x0010

#define GLFW_MOD_NUM_LOCK 0x0020

#define GLFW_MOUSE_BUTTON_1 0

#define GLFW_MOUSE_BUTTON_2 1

#define GLFW_MOUSE_BUTTON_3 2

#define GLFW_MOUSE_BUTTON_4 3

#define GLFW_MOUSE_BUTTON_5 4

#define GLFW_MOUSE_BUTTON_6 5

#define GLFW_MOUSE_BUTTON_7 6

#define GLFW_MOUSE_BUTTON_8 7

#define GLFW_MOUSE_BUTTON_LAST GLFW_MOUSE_BUTTON_8

#define GLFW_MOUSE_BUTTON_LEFT GLFW_MOUSE_BUTTON_1

#define GLFW_MOUSE_BUTTON_RIGHT GLFW_MOUSE_BUTTON_2

#define GLFW_MOUSE_BUTTON_MIDDLE GLFW_MOUSE_BUTTON_3

#define GLFW_JOYSTICK_1 0

#define GLFW_JOYSTICK_2 1

#define GLFW_JOYSTICK_3 2

#define GLFW_JOYSTICK_4 3

#define GLFW_JOYSTICK_5 4

#define GLFW_JOYSTICK_6 5

#define GLFW_JOYSTICK_7 6

#define GLFW_JOYSTICK_8 7

#define GLFW_JOYSTICK_9 8

#define GLFW_JOYSTICK_10 9

#define GLFW_JOYSTICK_11 10

#define GLFW_JOYSTICK_12 11

#define GLFW_JOYSTICK_13 12

#define GLFW_JOYSTICK_14 13

#define GLFW_JOYSTICK_15 14

#define GLFW_JOYSTICK_16 15

#define GLFW_JOYSTICK_LAST GLFW_JOYSTICK_16

#define GLFW_GAMEPAD_BUTTON_A 0

#define GLFW_GAMEPAD_BUTTON_B 1

#define GLFW_GAMEPAD_BUTTON_X 2

#define GLFW_GAMEPAD_BUTTON_Y 3

#define GLFW_GAMEPAD_BUTTON_LEFT_BUMPER 4

#define GLFW_GAMEPAD_BUTTON_RIGHT_BUMPER 5

#define GLFW_GAMEPAD_BUTTON_BACK 6

#define GLFW_GAMEPAD_BUTTON_START 7

#define GLFW_GAMEPAD_BUTTON_GUIDE 8

#define GLFW_GAMEPAD_BUTTON_LEFT_THUMB 9

#define GLFW_GAMEPAD_BUTTON_RIGHT_THUMB 10

#define GLFW_GAMEPAD_BUTTON_DPAD_UP 11

#define GLFW_GAMEPAD_BUTTON_DPAD_RIGHT 12

#define GLFW_GAMEPAD_BUTTON_DPAD_DOWN 13

#define GLFW_GAMEPAD_BUTTON_DPAD_LEFT 14

#define GLFW_GAMEPAD_BUTTON_LAST GLFW_GAMEPAD_BUTTON_DPAD_LEFT

#define GLFW_GAMEPAD_BUTTON_CROSS GLFW_GAMEPAD_BUTTON_A

#define GLFW_GAMEPAD_BUTTON_CIRCLE GLFW_GAMEPAD_BUTTON_B

#define GLFW_GAMEPAD_BUTTON_SQUARE GLFW_GAMEPAD_BUTTON_X

#define GLFW_GAMEPAD_BUTTON_TRIANGLE GLFW_GAMEPAD_BUTTON_Y

#define GLFW_GAMEPAD_AXIS_LEFT_X 0

#define GLFW_GAMEPAD_AXIS_LEFT_Y 1

#define GLFW_GAMEPAD_AXIS_RIGHT_X 2

#define GLFW_GAMEPAD_AXIS_RIGHT_Y 3

#define GLFW_GAMEPAD_AXIS_LEFT_TRIGGER 4

#define GLFW_GAMEPAD_AXIS_RIGHT_TRIGGER 5

#define GLFW_GAMEPAD_AXIS_LAST GLFW_GAMEPAD_AXIS_RIGHT_TRIGGER

#define GLFW_NO_ERROR 0

#define GLFW_NOT_INITIALIZED 0x00010001

#define GLFW_NO_CURRENT_CONTEXT 0x00010002

#define GLFW_INVALID_ENUM 0x00010003

#define GLFW_INVALID_VALUE 0x00010004

#define GLFW_OUT_OF_MEMORY 0x00010005

#define GLFW_API_UNAVAILABLE 0x00010006

#define GLFW_VERSION_UNAVAILABLE 0x00010007

#define GLFW_PLATFORM_ERROR 0x00010008

#define GLFW_FORMAT_UNAVAILABLE 0x00010009

#define GLFW_NO_WINDOW_CONTEXT 0x0001000A

#define GLFW_CURSOR_UNAVAILABLE 0x0001000B

#define GLFW_FEATURE_UNAVAILABLE 0x0001000C

#define GLFW_FEATURE_UNIMPLEMENTED 0x0001000D

#define GLFW_PLATFORM_UNAVAILABLE 0x0001000E

#define GLFW_FOCUSED 0x00020001

#define GLFW_ICONIFIED 0x00020002

#define GLFW_RESIZABLE 0x00020003

#define GLFW_VISIBLE 0x00020004

#define GLFW_DECORATED 0x00020005

#define GLFW_AUTO_ICONIFY 0x00020006

#define GLFW_FLOATING 0x00020007

#define GLFW_MAXIMIZED 0x00020008

#define GLFW_CENTER_CURSOR 0x00020009

#define GLFW_TRANSPARENT_FRAMEBUFFER 0x0002000A

#define GLFW_HOVERED 0x0002000B

#define GLFW_FOCUS_ON_SHOW 0x0002000C

#define GLFW_MOUSE_PASSTHROUGH 0x0002000D

#define GLFW_POSITION_X 0x0002000E

#define GLFW_POSITION_Y 0x0002000F

#define GLFW_RED_BITS 0x00021001

#define GLFW_GREEN_BITS 0x00021002

#define GLFW_BLUE_BITS 0x00021003

#define GLFW_ALPHA_BITS 0x00021004

#define GLFW_DEPTH_BITS 0x00021005

#define GLFW_STENCIL_BITS 0x00021006

#define GLFW_ACCUM_RED_BITS 0x00021007

#define GLFW_ACCUM_GREEN_BITS 0x00021008

#define GLFW_ACCUM_BLUE_BITS 0x00021009

#define GLFW_ACCUM_ALPHA_BITS 0x0002100A

#define GLFW_AUX_BUFFERS 0x0002100B

#define GLFW_STEREO 0x0002100C

#define GLFW_SAMPLES 0x0002100D

#define GLFW_SRGB_CAPABLE 0x0002100E

#define GLFW_REFRESH_RATE 0x0002100F

#define GLFW_DOUBLEBUFFER 0x00021010

#define GLFW_CLIENT_API 0x00022001

#define GLFW_CONTEXT_VERSION_MAJOR 0x00022002

#define GLFW_CONTEXT_VERSION_MINOR 0x00022003

#define GLFW_CONTEXT_REVISION 0x00022004

#define GLFW_CONTEXT_ROBUSTNESS 0x00022005

#define GLFW_OPENGL_FORWARD_COMPAT 0x00022006

#define GLFW_CONTEXT_DEBUG 0x00022007

#define GLFW_OPENGL_DEBUG_CONTEXT GLFW_CONTEXT_DEBUG

#define GLFW_OPENGL_PROFILE 0x00022008

#define GLFW_CONTEXT_RELEASE_BEHAVIOR 0x00022009

#define GLFW_CONTEXT_NO_ERROR 0x0002200A

#define GLFW_CONTEXT_CREATION_API 0x0002200B

#define GLFW_SCALE_TO_MONITOR 0x0002200C

#define GLFW_SCALE_FRAMEBUFFER 0x0002200D

#define GLFW_COCOA_RETINA_FRAMEBUFFER 0x00023001

#define GLFW_COCOA_FRAME_NAME 0x00023002

#define GLFW_COCOA_GRAPHICS_SWITCHING 0x00023003

#define GLFW_X11_CLASS_NAME 0x00024001

#define GLFW_X11_INSTANCE_NAME 0x00024002

#define GLFW_WIN32_KEYBOARD_MENU 0x00025001

#define GLFW_WIN32_SHOWDEFAULT 0x00025002

#define GLFW_WAYLAND_APP_ID 0x00026001

#define GLFW_NO_API 0

#define GLFW_OPENGL_API 0x00030001

#define GLFW_OPENGL_ES_API 0x00030002

#define GLFW_NO_ROBUSTNESS 0

#define GLFW_NO_RESET_NOTIFICATION 0x00031001

#define GLFW_LOSE_CONTEXT_ON_RESET 0x00031002

#define GLFW_OPENGL_ANY_PROFILE 0

#define GLFW_OPENGL_CORE_PROFILE 0x00032001

#define GLFW_OPENGL_COMPAT_PROFILE 0x00032002

#define GLFW_CURSOR 0x00033001

#define GLFW_STICKY_KEYS 0x00033002

#define GLFW_STICKY_MOUSE_BUTTONS 0x00033003

#define GLFW_LOCK_KEY_MODS 0x00033004

#define GLFW_RAW_MOUSE_MOTION 0x00033005

#define GLFW_CURSOR_NORMAL 0x00034001

#define GLFW_CURSOR_HIDDEN 0x00034002

#define GLFW_CURSOR_DISABLED 0x00034003

#define GLFW_CURSOR_CAPTURED 0x00034004

#define GLFW_ANY_RELEASE_BEHAVIOR 0

#define GLFW_RELEASE_BEHAVIOR_FLUSH 0x00035001

#define GLFW_RELEASE_BEHAVIOR_NONE 0x00035002

#define GLFW_NATIVE_CONTEXT_API 0x00036001

#define GLFW_EGL_CONTEXT_API 0x00036002

#define GLFW_OSMESA_CONTEXT_API 0x00036003

#define GLFW_ANGLE_PLATFORM_TYPE_NONE 0x00037001

#define GLFW_ANGLE_PLATFORM_TYPE_OPENGL 0x00037002

#define GLFW_ANGLE_PLATFORM_TYPE_OPENGLES 0x00037003

#define GLFW_ANGLE_PLATFORM_TYPE_D3D9 0x00037004

#define GLFW_ANGLE_PLATFORM_TYPE_D3D11 0x00037005

#define GLFW_ANGLE_PLATFORM_TYPE_VULKAN 0x00037007

#define GLFW_ANGLE_PLATFORM_TYPE_METAL 0x00037008

#define GLFW_WAYLAND_PREFER_LIBDECOR 0x00038001

#define GLFW_WAYLAND_DISABLE_LIBDECOR 0x00038002

#define GLFW_ANY_POSITION 0x80000000

#define GLFW_ARROW_CURSOR 0x00036001

#define GLFW_IBEAM_CURSOR 0x00036002

#define GLFW_CROSSHAIR_CURSOR 0x00036003

#define GLFW_POINTING_HAND_CURSOR 0x00036004

#define GLFW_RESIZE_EW_CURSOR 0x00036005

#define GLFW_RESIZE_NS_CURSOR 0x00036006

#define GLFW_RESIZE_NWSE_CURSOR 0x00036007

#define GLFW_RESIZE_NESW_CURSOR 0x00036008

#define GLFW_RESIZE_ALL_CURSOR 0x00036009

#define GLFW_NOT_ALLOWED_CURSOR 0x0003600A

#define GLFW_HRESIZE_CURSOR GLFW_RESIZE_EW_CURSOR

#define GLFW_VRESIZE_CURSOR GLFW_RESIZE_NS_CURSOR

#define GLFW_HAND_CURSOR GLFW_POINTING_HAND_CURSOR

#define GLFW_CONNECTED 0x00040001

#define GLFW_DISCONNECTED 0x00040002

#define GLFW_JOYSTICK_HAT_BUTTONS 0x00050001

#define GLFW_ANGLE_PLATFORM_TYPE 0x00050002

#define GLFW_PLATFORM 0x00050003

#define GLFW_COCOA_CHDIR_RESOURCES 0x00051001

#define GLFW_COCOA_MENUBAR 0x00051002

#define GLFW_X11_XCB_VULKAN_SURFACE 0x00052001

#define GLFW_WAYLAND_LIBDECOR 0x00053001

#define GLFW_ANY_PLATFORM 0x00060000

#define GLFW_PLATFORM_WIN32 0x00060001

#define GLFW_PLATFORM_COCOA 0x00060002

#define GLFW_PLATFORM_WAYLAND 0x00060003

#define GLFW_PLATFORM_X11 0x00060004

#define GLFW_PLATFORM_NULL 0x00060005

#define GLFW_DONT_CARE -1





struct GLFWmonitor {
    uint8_t _jbg_opaque;
};
static GLFWmonitor _j_struct_GLFWmonitor_default(void) { GLFWmonitor value; memset(&value, 0, sizeof(value)); return value; }
static GLFWmonitor *_j_struct_GLFWmonitor_new(void) { GLFWmonitor *value = (GLFWmonitor*)calloc(1, sizeof(GLFWmonitor)); if (!value) abort(); return value; }

struct GLFWwindow {
    uint8_t _jbg_opaque;
};
static GLFWwindow _j_struct_GLFWwindow_default(void) { GLFWwindow value; memset(&value, 0, sizeof(value)); return value; }
static GLFWwindow *_j_struct_GLFWwindow_new(void) { GLFWwindow *value = (GLFWwindow*)calloc(1, sizeof(GLFWwindow)); if (!value) abort(); return value; }

struct GLFWcursor {
    uint8_t _jbg_opaque;
};
static GLFWcursor _j_struct_GLFWcursor_default(void) { GLFWcursor value; memset(&value, 0, sizeof(value)); return value; }
static GLFWcursor *_j_struct_GLFWcursor_new(void) { GLFWcursor *value = (GLFWcursor*)calloc(1, sizeof(GLFWcursor)); if (!value) abort(); return value; }















































struct GLFWvidmode {
    int32_t width;
    int32_t height;
    int32_t redBits;
    int32_t greenBits;
    int32_t blueBits;
    int32_t refreshRate;
};
static GLFWvidmode _j_struct_GLFWvidmode_default(void) { GLFWvidmode value; memset(&value, 0, sizeof(value)); return value; }
static GLFWvidmode *_j_struct_GLFWvidmode_new(void) { GLFWvidmode *value = (GLFWvidmode*)calloc(1, sizeof(GLFWvidmode)); if (!value) abort(); return value; }

struct GLFWgammaramp {
    uint16_t * red;
    uint16_t * green;
    uint16_t * blue;
    uint32_t size;
};
static GLFWgammaramp _j_struct_GLFWgammaramp_default(void) { GLFWgammaramp value; memset(&value, 0, sizeof(value)); return value; }
static GLFWgammaramp *_j_struct_GLFWgammaramp_new(void) { GLFWgammaramp *value = (GLFWgammaramp*)calloc(1, sizeof(GLFWgammaramp)); if (!value) abort(); return value; }

struct GLFWimage {
    int32_t width;
    int32_t height;
    uint8_t * pixels;
};
static GLFWimage _j_struct_GLFWimage_default(void) { GLFWimage value; memset(&value, 0, sizeof(value)); return value; }
static GLFWimage *_j_struct_GLFWimage_new(void) { GLFWimage *value = (GLFWimage*)calloc(1, sizeof(GLFWimage)); if (!value) abort(); return value; }

struct GLFWgamepadstate {
    uint8_t _jbg_opaque;
};
static GLFWgamepadstate _j_struct_GLFWgamepadstate_default(void) { GLFWgamepadstate value; memset(&value, 0, sizeof(value)); return value; }
static GLFWgamepadstate *_j_struct_GLFWgamepadstate_new(void) { GLFWgamepadstate *value = (GLFWgamepadstate*)calloc(1, sizeof(GLFWgamepadstate)); if (!value) abort(); return value; }

struct GLFWallocator {
    void * (*allocate)(uint64_t, void *);
    void * (*reallocate)(void *, uint64_t, void *);
    void (*deallocate)(void *, void *);
    void * user;
};
static GLFWallocator _j_struct_GLFWallocator_default(void) { GLFWallocator value; memset(&value, 0, sizeof(value)); return value; }
static GLFWallocator *_j_struct_GLFWallocator_new(void) { GLFWallocator *value = (GLFWallocator*)calloc(1, sizeof(GLFWallocator)); if (!value) abort(); return value; }

int32_t glfwInit(void);

void glfwTerminate(void);

void glfwInitHint(int32_t hint, int32_t value);

void glfwInitAllocator(GLFWallocator * allocator);

void glfwGetVersion(int32_t * major, int32_t * minor, int32_t * rev);

int8_t * glfwGetVersionString(void);

int32_t glfwGetError(int8_t * * description);

void (*glfwSetErrorCallback(void (*callback)(int32_t, int8_t *)))(int32_t, int8_t *);

int32_t glfwGetPlatform(void);

int32_t glfwPlatformSupported(int32_t platform);

GLFWmonitor * * glfwGetMonitors(int32_t * count);

GLFWmonitor * glfwGetPrimaryMonitor(void);

void glfwGetMonitorPos(GLFWmonitor * monitor, int32_t * xpos, int32_t * ypos);

void glfwGetMonitorWorkarea(GLFWmonitor * monitor, int32_t * xpos, int32_t * ypos, int32_t * width, int32_t * height);

void glfwGetMonitorPhysicalSize(GLFWmonitor * monitor, int32_t * widthMM, int32_t * heightMM);

void glfwGetMonitorContentScale(GLFWmonitor * monitor, float * xscale, float * yscale);

int8_t * glfwGetMonitorName(GLFWmonitor * monitor);

void glfwSetMonitorUserPointer(GLFWmonitor * monitor, void * pointer);

void * glfwGetMonitorUserPointer(GLFWmonitor * monitor);

void (*glfwSetMonitorCallback(void (*callback)(GLFWmonitor *, int32_t)))(GLFWmonitor *, int32_t);

GLFWvidmode * glfwGetVideoModes(GLFWmonitor * monitor, int32_t * count);

GLFWvidmode * glfwGetVideoMode(GLFWmonitor * monitor);

void glfwSetGamma(GLFWmonitor * monitor, float gamma);

GLFWgammaramp * glfwGetGammaRamp(GLFWmonitor * monitor);

void glfwSetGammaRamp(GLFWmonitor * monitor, GLFWgammaramp * ramp);

void glfwDefaultWindowHints(void);

void glfwWindowHint(int32_t hint, int32_t value);

void glfwWindowHintString(int32_t hint, int8_t * value);

GLFWwindow * glfwCreateWindow(int32_t width, int32_t height, int8_t * title, GLFWmonitor * monitor, GLFWwindow * share);

void glfwDestroyWindow(GLFWwindow * window);

int32_t glfwWindowShouldClose(GLFWwindow * window);

void glfwSetWindowShouldClose(GLFWwindow * window, int32_t value);

int8_t * glfwGetWindowTitle(GLFWwindow * window);

void glfwSetWindowTitle(GLFWwindow * window, int8_t * title);

void glfwSetWindowIcon(GLFWwindow * window, int32_t count, GLFWimage * images);

void glfwGetWindowPos(GLFWwindow * window, int32_t * xpos, int32_t * ypos);

void glfwSetWindowPos(GLFWwindow * window, int32_t xpos, int32_t ypos);

void glfwGetWindowSize(GLFWwindow * window, int32_t * width, int32_t * height);

void glfwSetWindowSizeLimits(GLFWwindow * window, int32_t minwidth, int32_t minheight, int32_t maxwidth, int32_t maxheight);

void glfwSetWindowAspectRatio(GLFWwindow * window, int32_t numer, int32_t denom);

void glfwSetWindowSize(GLFWwindow * window, int32_t width, int32_t height);

void glfwGetFramebufferSize(GLFWwindow * window, int32_t * width, int32_t * height);

void glfwGetWindowFrameSize(GLFWwindow * window, int32_t * left, int32_t * top, int32_t * right, int32_t * bottom);

void glfwGetWindowContentScale(GLFWwindow * window, float * xscale, float * yscale);

float glfwGetWindowOpacity(GLFWwindow * window);

void glfwSetWindowOpacity(GLFWwindow * window, float opacity);

void glfwIconifyWindow(GLFWwindow * window);

void glfwRestoreWindow(GLFWwindow * window);

void glfwMaximizeWindow(GLFWwindow * window);

void glfwShowWindow(GLFWwindow * window);

void glfwHideWindow(GLFWwindow * window);

void glfwFocusWindow(GLFWwindow * window);

void glfwRequestWindowAttention(GLFWwindow * window);

GLFWmonitor * glfwGetWindowMonitor(GLFWwindow * window);

void glfwSetWindowMonitor(GLFWwindow * window, GLFWmonitor * monitor, int32_t xpos, int32_t ypos, int32_t width, int32_t height, int32_t refreshRate);

int32_t glfwGetWindowAttrib(GLFWwindow * window, int32_t attrib);

void glfwSetWindowAttrib(GLFWwindow * window, int32_t attrib, int32_t value);

void glfwSetWindowUserPointer(GLFWwindow * window, void * pointer);

void * glfwGetWindowUserPointer(GLFWwindow * window);

void (*glfwSetWindowPosCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t, int32_t)))(GLFWwindow *, int32_t, int32_t);

void (*glfwSetWindowSizeCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t, int32_t)))(GLFWwindow *, int32_t, int32_t);

void (*glfwSetWindowCloseCallback(GLFWwindow * window, void (*callback)(GLFWwindow *)))(GLFWwindow *);

void (*glfwSetWindowRefreshCallback(GLFWwindow * window, void (*callback)(GLFWwindow *)))(GLFWwindow *);

void (*glfwSetWindowFocusCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t)))(GLFWwindow *, int32_t);

void (*glfwSetWindowIconifyCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t)))(GLFWwindow *, int32_t);

void (*glfwSetWindowMaximizeCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t)))(GLFWwindow *, int32_t);

void (*glfwSetFramebufferSizeCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t, int32_t)))(GLFWwindow *, int32_t, int32_t);

void (*glfwSetWindowContentScaleCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, float, float)))(GLFWwindow *, float, float);

void glfwPollEvents(void);

void glfwWaitEvents(void);

void glfwWaitEventsTimeout(double timeout);

void glfwPostEmptyEvent(void);

int32_t glfwGetInputMode(GLFWwindow * window, int32_t mode);

void glfwSetInputMode(GLFWwindow * window, int32_t mode, int32_t value);

int32_t glfwRawMouseMotionSupported(void);

int8_t * glfwGetKeyName(int32_t key, int32_t scancode);

int32_t glfwGetKeyScancode(int32_t key);

int32_t glfwGetKey(GLFWwindow * window, int32_t key);

int32_t glfwGetMouseButton(GLFWwindow * window, int32_t button);

void glfwGetCursorPos(GLFWwindow * window, double * xpos, double * ypos);

void glfwSetCursorPos(GLFWwindow * window, double xpos, double ypos);

GLFWcursor * glfwCreateCursor(GLFWimage * image, int32_t xhot, int32_t yhot);

GLFWcursor * glfwCreateStandardCursor(int32_t shape);

void glfwDestroyCursor(GLFWcursor * cursor);

void glfwSetCursor(GLFWwindow * window, GLFWcursor * cursor);

void (*glfwSetKeyCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t, int32_t, int32_t, int32_t)))(GLFWwindow *, int32_t, int32_t, int32_t, int32_t);

void (*glfwSetCharCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, uint32_t)))(GLFWwindow *, uint32_t);

void (*glfwSetCharModsCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, uint32_t, int32_t)))(GLFWwindow *, uint32_t, int32_t);

void (*glfwSetMouseButtonCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t, int32_t, int32_t)))(GLFWwindow *, int32_t, int32_t, int32_t);

void (*glfwSetCursorPosCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, double, double)))(GLFWwindow *, double, double);

void (*glfwSetCursorEnterCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t)))(GLFWwindow *, int32_t);

void (*glfwSetScrollCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, double, double)))(GLFWwindow *, double, double);

void (*glfwSetDropCallback(GLFWwindow * window, void (*callback)(GLFWwindow *, int32_t, int8_t * *)))(GLFWwindow *, int32_t, int8_t * *);

int32_t glfwJoystickPresent(int32_t jid);

float * glfwGetJoystickAxes(int32_t jid, int32_t * count);

uint8_t * glfwGetJoystickButtons(int32_t jid, int32_t * count);

uint8_t * glfwGetJoystickHats(int32_t jid, int32_t * count);

int8_t * glfwGetJoystickName(int32_t jid);

int8_t * glfwGetJoystickGUID(int32_t jid);

void glfwSetJoystickUserPointer(int32_t jid, void * pointer);

void * glfwGetJoystickUserPointer(int32_t jid);

int32_t glfwJoystickIsGamepad(int32_t jid);

void (*glfwSetJoystickCallback(void (*callback)(int32_t, int32_t)))(int32_t, int32_t);

int32_t glfwUpdateGamepadMappings(int8_t * string_);

int8_t * glfwGetGamepadName(int32_t jid);

int32_t glfwGetGamepadState(int32_t jid, GLFWgamepadstate * state);

void glfwSetClipboardString(GLFWwindow * window, int8_t * string_);

int8_t * glfwGetClipboardString(GLFWwindow * window);

double glfwGetTime(void);

void glfwSetTime(double time);

uint64_t glfwGetTimerValue(void);

uint64_t glfwGetTimerFrequency(void);

void glfwMakeContextCurrent(GLFWwindow * window);

GLFWwindow * glfwGetCurrentContext(void);

void glfwSwapBuffers(GLFWwindow * window);

void glfwSwapInterval(int32_t interval);

int32_t glfwExtensionSupported(int8_t * extension);

void (*glfwGetProcAddress(int8_t * procname))(void);

int32_t glfwVulkanSupported(void);

int8_t * * glfwGetRequiredInstanceExtensions(uint32_t * count);

int main(int _j_main_argc, char *_j_main_argv[]) {
    string *param = string_from_cstr((_j_main_argc > 1) ? _j_main_argv[1] : "");
    int32_t ok = glfwInit();
    GLFWwindow * win = glfwCreateWindow(800, 600, "Ma fenetre", ((void*)0), ((void*)0));
    while (glfwWindowShouldClose(win) == 0) {
        glfwPollEvents();
    }
    glfwDestroyWindow(win);
    glfwTerminate();
    return 0;
}
