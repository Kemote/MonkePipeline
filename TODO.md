add own path resolver for USD file, path resolver to obtain path, based on os
for example in exporter.py should get path form separate object and base in on outputType


Create path resolver which will be used to resolve path based on project root and using versions token to get correct version, system should recognize the token and get newest version if user dont set different behavior. now it's time to thing how should it be used. If it should be fast and efficient database, or something else? Maybe we should use some approve system which recognize evrything? Or maybe there should be an option to set it in databse? So lead can change approved version of materials, binding and models so no need to change main file evrytime? need to check that it even more improtant than all varaints etc...

TODO: create separate branch from baseMaterialsVaraints to create that, jsut after you get rid of material varaints...