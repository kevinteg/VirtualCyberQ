=================================
Virtual CyberQ BBQ XML web server
=================================

A simple web server hosting virtual data for the CyberQ BBQ control unit.  See https://www.bbqguru.com/.

This was inspired by https://github.com/thebrilliantidea/CyberQInterface.  I ordered the CyberQ control unit
but it hasn't shipped yet so I decided to create a virtual one for now based on the work in this project.  The
library *should* work against this virtual server but it does not accurately reflect the behavior of a real CyberQ unit yet.
When I receive the CyberQ I will spend some more time improving this implementation.

TODO
====

* Implement temperature control behavior (increase when set > temp, etc)
* Update default values with real factory defaults
* Refactor mapping between object attributes and xml attributes (a bit hacky right now)
* Provide defaults in flask launch (or read from config, defaults file?)
* WAY more error handling.  I currently rely on the parameter validation done by CyberQInterface but this should emulate what the real unit does.

