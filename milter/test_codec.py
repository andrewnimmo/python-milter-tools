#
# TODO: we should have some real, validated binary messages so that we can
# test proper interoperability.

import unittest, struct

import codec
from consts import *

# This may violate the tenets of (unit)testing, since this is not an
# exposed interface of the codec module but instead an internal
# implementation detail. I am testing it directly because I want to
# know if encoding or decoding a particular type of thing fails,
# rather than inferring it through the failure of various message
# encoding/decoding tests.
class codingTests(unittest.TestCase):
	ctypes = (
		('char', 'A'),
		('char3', 'abc'),
		('u16', 10),
		('u32', 30000),
		('str', 'a long string'),
		('strn0', 'a long string mark 2'),
		('strs', ['a', 'b', 'c', ]),
		('strpairs', ['d', 'e', 'f', 'g', 'h', 'i',]),

		# Corner case for strings
		('str', ''),
		('strn0', ''),
		('strs', ['a', '']),
		('strpairs', []),
		# these are corner cases for unsigned int ranges
		('u16', (2**16)-1),
		('u32', (2**32)-1),
		)

	def testEncodeDecode(self):
		"""Test that we can encode and then decode an example of
		every known type."""
		for ctype, val in self.ctypes:
			d = codec.encode(ctype, val)
			r, d2 = codec.decode(ctype, d)
			self.assertEqual(val, r)
			# also, nothing left over from the data
			self.assertEqual(d2, '')

	def testStrN0(self):
		"""Test that strn0 decodes a non-zero-terminated string."""
		# We cannot test this above because we do not generate such
		# strings.
		tstr = "abcdef"
		self.assertEqual(codec.decode("strn0", tstr), (tstr, ''))

	# Test bad encodes that should error out.
	bencs = (
		('char3', 'a'),
		('char3', 'abcd'),
		('strs', []),
		('strpairs', ['a',]),
		)
	def testBadEncode(self):
		"""Test that certain things fail to encode with errors."""
		for ctype, val in self.bencs:
			self.assertRaises(codec.MilterProtoError,
					  codec.encode, ctype, val)

	bdecs = (
		# No terminating \0
		('str', 'abcdef'),
		# uneven number of pairs
		('strpairs', 'abc\0def\0ghi\0'),
		# No strings in string array
		('strs', ''),
		)
	def testBadDecode(self):
		"""Test that certain things fail to decode."""
		for ctype, data in self.bdecs:
			self.assertRaises(codec.MilterProtoError,
					  codec.decode, ctype, data)
		

# A sample message for every milter protocol message that we know about.
sample_msgs = [
	('A', {}),
	('B', {'buf': 'abcdefghi\nthis is a test, yes.\n\t-cks'}),
	('C', {'hostname': 'localhost', 'family': '4', 'port': 3000,
	       'address': '127.0.0.1'}),
	('D', {'cmdcode': 'R', 'nameval': ['rcpt_mailer', 'abc',
					   'rcpt_host', 'localhost',
					   'rcpt_addr', 'cks']}),
	('E', {}),
	('H', {'helo': 'localhost.localdomain'}),
	('L', {'name': 'Subject', 'value': 'Tedium'}),
	('M', {'args': ['<>', 'haha']}),
	('N', {}),
	('O', {'version': 2, 'actions': 0x01, 'protocol': 0x02}),
	('R', {'args': ['<nosuch@cs.toronto.edu>', 'SIZE=100']}),
	('Q', {}),

	('+', {'rcpt': '<suchno@toronto.edu>'}),
	('-', {'rcpt': '<isthere@toronto.edu>'}),
	('a', {}),
	('b', {'buf': 'ARGLEBARGLE TEDIUM'}),
	('c', {}),
	('d', {}),
	('h', {'name': 'X-Annoyance', 'value': 'Testing'}),
	('m', {'index': 10, 'name': 'X-Spam-Goblets', 'value': '100% canned'}),
	('p', {}),
	('q', {'reason': 'Your mother was an Englishman'}),
	('r', {}),
	('t', {}),
	('y', {'smtpcode': '450', 'space': ' ', 'text': 'lazyness strikes'}),

	# It is explicitly valid to have an empty value for a modified
	# header; this deletes the header. We test that we can at least
	# generate such a message.
	('m', {'index': 1, 'name': 'Subject', 'value': ''}),
	# Macros can be empty.
	('D', {'cmdcode': 'H', 'nameval': []}),
	]

class basicTests(unittest.TestCase):
	def testMessageEncode(self):
		"""Can we encode every sample message to a non-zero message
		that has the cmd code as its fifth character?"""
		for cmd, args in sample_msgs:
			r = codec.encode_msg(cmd, **args)
			self.assertNotEqual(len(r), 0)
			self.assertTrue(len(r) >= 5)
			self.assertEqual(r[4], cmd)
			if not args:
				self.assertEqual(len(r), 5)

	def testMessageDecode(self):
		"""Test that encoded messages decode back to something that
		is identical to what we started with."""
		suffix = "\nabc"
		for cmd, args in sample_msgs:
			r = codec.encode_msg(cmd, **args)
			dcmd, dargs, rest = codec.decode_msg(r)
			self.assertEqual(cmd, dcmd)
			self.assertEqual(args, dargs)
			self.assertEqual(rest, '')
			# As a bonus, test that decoding with more data works
			# right for all messages.
			dcmd, dargs, rest = codec.decode_msg(r + suffix)
			self.assertEqual(rest, suffix)

	def testTruncatedDecode(self):
		"""Test that we signal not-enough on truncated decodes."""
		for cmd, args in sample_msgs:
			r = codec.encode_msg(cmd, **args)
			r = r[:-1]
			self.assertRaises(codec.MilterIncomplete,
					  codec.decode_msg, r)

	def testBrokenCommands(self):
		"""Sleazily test that we signal errors on malformed packets."""
		# Encode something that has no arguments.
		r = codec.encode_msg('A')
		# Break the command byte to something that doesn't exist.
		r = r[:4] + '!'
		self.assertRaises(codec.MilterDecodeError,
				  codec.decode_msg, r)
		# Break the command byte to something that requires arguments.
		r = r[:4] + 'D'
		self.assertRaises(codec.MilterDecodeError,
				  codec.decode_msg, r)

	# Change the claimed length of a message by delta (may be positive
	# or negative). If this lengthens the message, you need to supply
	# extra actual data yourself.
	def _changelen(self, msg, delta):
		tlen = struct.unpack("!L", msg[:4])[0]
		tlen = tlen + delta
		if tlen <= 0:
			raise IndexError("new length too short")
		return struct.pack("!L", tlen) + msg[4:]
	def testBrokenLength(self):
		"""Sleazily test for a too-short version of every message."""
		minlen = struct.pack("!L", 1)
		for cmd, args in sample_msgs:
			# We can't shorten a message that has no arguments.
			if not args:
				continue
			# Because of stupidity seen in real life, we can't
			# shorten REPLBODY messages
			if cmd == SMFIR_REPLBODY:
				continue
			r = codec.encode_msg(cmd, **args)
			r = self._changelen(r, -1)
			self.assertRaises(codec.MilterDecodeError,
					  codec.decode_msg, r)
			# See what happens with a minimum-length message.
			r = minlen + r[4:]
			self.assertRaises(codec.MilterDecodeError,
					  codec.decode_msg, r)

	def testExtraLength(self):
		"""Sleazily test that messages with extra packet data
		fail to decode."""
		for cmd, args in sample_msgs:
			r = codec.encode_msg(cmd, **args)
			# remember: we've got to supply the actual extra
			# data, or we just get a 'message incomplete' note.
			r = self._changelen(r, +10) + ("*" * 10)
			self.assertRaises(codec.MilterDecodeError,
					  codec.decode_msg, r)
			

	def testZeroLength(self):
		"""Trying to decode a zero-length message should fail with
		a decode error."""
		zlen = struct.pack("!L", 0)
		self.assertRaises(codec.MilterDecodeError,
				  codec.decode_msg, zlen)

	def testExtraArgsEncode(self):
		"""Test that adding arguments results in an encode error."""
		for cmd, args in sample_msgs:
			args = args.copy()
			args['blarg'] = 10
			self.assertRaises(codec.MilterProtoError,
					  codec.encode_msg, cmd,
					  **args)
	def testMissingArgsEncode(self):
		"""Test that removing arguments results in an encode error."""
		for cmd, args in sample_msgs:
			# Can't remove an argument if we don't have one
			if not args:
				continue
			args = args.copy()
			args.popitem()
			self.assertRaises(codec.MilterProtoError,
					  codec.encode_msg, cmd,
					  **args)

if __name__ == "__main__":
	unittest.main()
