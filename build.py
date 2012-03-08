import atexit
import logging
import os
import tempfile

class Builder(object):

	def __init__(self,config):

		self.logf = logging.getLogger('Builder')

		self.pathToGpp = config['path.g++']
		self.pathToBotcore = config['path.q2botcore']
		self.workingDir = os.path.abspath(config['path.workspace'])

		self.cflags = config['build.cflags']
		self.ldflags = config['build.ldflags']
		
		self.includePaths = [ self.pathToBotcore ]
		self.libPaths = [ self.pathToBotcore ]
		self.libs = config['build.libs']
		self.srcFiles = map(lambda x: self.pathToBotcore + '/' + x, config['q2botcore.src'])
		
	def compile(self, bot):
		
		# Construct the command line
		args = [self.pathToGpp]
		for includeDir in self.includePaths:
			args.append("-I" + includeDir)

		for libDir in self.libPaths:
			args.append("-L" + libDir)

		# Build the command line.
		if self.cflags:
			map(args.append, self.cflags.split())
		if self.ldflags:
			map(args.append, self.ldflags.split())
		
		# Create the source file
		botDir = self.workingDir + '/' + bot.name
		codePath = botDir + '/' + bot.name + '.cpp'
		outputPath = botDir + '/runbot'

		if not os.path.exists(botDir):
			os.makedirs(botDir)
		fp = open(codePath, 'w')
		fp.write(bot.code)
		fp.close()
		
		# Specify output
		args.append("-o")
		args.append(outputPath)

		# Source files
		for file in self.srcFiles:
			args.append(file)
		args.append(codePath)
		
		# This option has to go at the end so that ld picks it up
		for lib in self.libs:
			args.append("-l" + lib)
		
		self.logf.debug(' '.join(args))
		
		# Run the command
		result = os.spawnv(os.P_WAIT, self.pathToGpp, args)
		if result == 0:
			bot.baseDir = botDir
			bot.exe = outputPath
			bot.srcFile = codePath

			return 0

		self.logf.warning('Failed to build %s', codePath)
		return result

	def clean(self,bot):
		
		self.logf.info('Cleaning up %s', bot.name)
		
		os.remove(bot.srcFile)
		os.remove(bot.exe)
