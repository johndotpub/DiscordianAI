from setuptools import setup, find_packages

setup(
    name='DiscordianAI',
    version='0.1.0',
    url='https://github.com/johndotpub/DiscordianAI',
    author='johndotpub',
    author_email='github@john.pub',
    description=('A Discord bot that uses OpenAI\'s GPT API to generate '
                 'responses to user messages.'),
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    packages=find_packages(),
    install_requires=[
        'discord.py>=1.7.3',  # Specify the minimum version requirement
        'openai>=0.10.2',     # Specify the minimum version requirement
        'python-dotenv>=0.19.0'  # Include missing dependency for environment variables
    ],
    python_requires='>=3.12',  # Specify the minimum Python version requirement
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: The Unlicense (Unlicense)',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.12',
        'Topic :: Communications :: Chat',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    entry_points={
        'console_scripts': [
            'discordianai=discordianai.__main__:main',
        ],
    },
)
