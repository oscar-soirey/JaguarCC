#include "api.h"

#include <stdio.h>

void (*callback)() = NULL;

void CallCallback()
{
	if (callback != NULL)
		callback();
}