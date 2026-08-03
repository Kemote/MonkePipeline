#include "resolver_db.h"
#include "resolver_disk.h"
#include "pxr/usd/ar/defineResolver.h" // USD macro helper to register our plugins.

// This file just aggregates every resolver implementation and registers it
// with USD. The resolvers themselves live in their own header/cpp pairs.
AR_DEFINE_RESOLVER(MonkeDbResolver, ArResolver);
AR_DEFINE_RESOLVER(MonkeDiskResolver, ArResolver);
