from setuptools import setup, find_packages

try:
    import multiprocessing
except ImportError:
    pass

setup(
    #Package information
    name = "VirtualCyberQ",
    description = "A simple web server hosting virtual data for the CyberQ BBQ control unit.",
    version = "0.0.1a",
    license = "BSD New",
    url = "https://github.com/kevinteg/VirtualCyberQ",   
    author = "Kevin Tegtmeier",
    author_email = "kevin@tegtmeier.me",
    
    #Package metadata
    keywords = "cyberq api bbq bbqguru",
    install_requires=['flask', 'jinja'],
    test_suite = "nose.collector",
    tests_require=['nose>=1.0.0', 'mock>=1.0.0', 'coverage'],
    packages = find_packages(),
    package_data = {
        # If any package contains *.txt or *.rst files, include them:
        #'': ['*.txt', '*.rst'],
        # And include any *.msg files found in the 'hello' package, too:
        #'hello': ['*.msg'],
    },
     # could also include long_description, download_url, classifiers, etc.
    )
