#include "resolver_disk.h"
#include "pxr/usd/ar/defineResolver.h"

// registers MonkeDiskResolver with USD as the handler for the monkeDisc:// scheme
AR_DEFINE_RESOLVER(MonkeDiskResolver, ArResolver);
