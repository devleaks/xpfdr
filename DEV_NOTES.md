# Development Notes

The first version of this project was a demonstration application of [X-Plane Web API](https://github.com/devleaks/xplane-webapi).
In the `examples` folder there is a basic FDR in `fdr.py`, `fdr.yaml`, `fdr_reader.py`.
This application is external to X-Plane, it connects through the Web API.

Since I wanted a faster, more direct access to datarefs, I moved the code to a X-Plane plugin.
In addition, with the "rules" that it implements, the plugin starts automatically all the time.
There is need to start an external application.
More or less like the real stuff.

Especially for ToLiss Airbus where I implemented Airbus DFDR logic into the plugin.