#pragma once

#define API_VERSION 1.0

typedef struct Resource Resource;

typedef void (*ResourceCallback)(
    Resource* resource,
    const void* data,
    size_t size,
    void* userdata
);

typedef void (*DestroyCallback)(void* userdata);

typedef struct ResourceDescriptor
{
    const char* name;

    size_t size;

    void* userdata;

    ResourceCallback callback;
    DestroyCallback destroy;

    const struct ResourceDescriptor* parent;

    union
    {
        int integer;
        float real;

        struct
        {
            const void* data;
            size_t size;
        } binary;

        struct
        {
            const char* const* strings;
            size_t count;
        } text;
    } value;
} ResourceDescriptor;

Resource* resource_create(
    const ResourceDescriptor* descriptor,
    Resource** dependencies,
    size_t dependency_count,
    void (*allocator)(
        void* userdata,
        size_t size,
        size_t alignment
    ),
    void* allocator_userdata
);