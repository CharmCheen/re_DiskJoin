#include "../utils/utils.h"
#include "../lib/DiskJoin.h"

int main(int argc, char** argv) {
   ConfigReader config_reader(argv[1]);
   Timer timer;
   DiskJoin index;
   timer.tick();
   index.build(config_reader);
   timer.tuck("Build done");
   index.search(config_reader);
   timer.tuck("Join done");
}