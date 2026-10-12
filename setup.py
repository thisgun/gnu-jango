from setuptools import setup, find_packages

setup(
    # 배포할 패키지의 이름을 적어줍니다. setup.py파일을 가지는 폴더 이름과 동일하게 합니다.
    name='gnu_jango',
    version='0.1',
    description='Gnuboard5 / YoungCart ported to Django and Next.js',
    # long_description=README,
    url='https://github.com/thisgun/jango_test',
    download_url = 'https://github.com/thisgun/jango_test/archive/master.zip',
    author='thisgun',
    author_email='thisgun@users.noreply.github.com',
    # 해당 패키지를 사용하기 위해 필요한 패키지를 적어줍니다. ex. install_requires= ['numpy', 'django']
    # 등록하고자 하는 패키지를 적는 곳입니다.
    # 우리는 find_packages 라이브러리를 이용하기 때문에 아래와 같이 적어줍니다.
    # 만약 제외하고자 하는 파일이 있다면 exclude에 적어줍니다.
    packages = find_packages(exclude = []),
    license='LGPL-2.1-or-later',
    # keywords            = ['gnu jango'],
    python_requires     = '>=3.12',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)',
        'Framework :: Django',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
    ],
    # 여기에 적어준 패키지는 현재 패키지를 install할때 함께 install됩니다.
    install_requires=[],
    zip_safe=False,
)