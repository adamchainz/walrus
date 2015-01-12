import datetime
import sys
import unittest

from walrus import *
from walrus.query import OP_AND
from walrus.query import OP_OR


db = Database(db=15)


class BaseModel(Model):
    database = db
    namespace = 'test'

class User(BaseModel):
    username = TextField(primary_key=True)

class Note(BaseModel):
    user = TextField(index=True)
    text = TextField()
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)
    tags = JSONField()

class Message(BaseModel):
    content = TextField(fts=True)
    status = IntegerField(default=1, index=True)

class FTSOptions(BaseModel):
    content = TextField(fts=True, stemmer=True)
    metaphone = TextField(fts=True, stemmer=True, metaphone=True)

class Stat(BaseModel):
    key = AutoIncrementField()
    stat_type = ByteField(index=True)
    value = IntegerField(index=True)


cache = db.cache(name='test.cache')


@cache.cached(timeout=60)
def now(seed=None):
    return datetime.datetime.now()


class WalrusTestCase(unittest.TestCase):
    def setUp(self):
        db.flushdb()
        db._transaction_local.pipes = []

    def tearDown(self):
        db.flushdb()
        db._transaction_local.pipes = []


class TestModels(WalrusTestCase):
    def create_objects(self):
        for i in range(3):
            u = User.create(username='u%s' % (i + 1))
            for j in range(3):
                Note.create(
                    user=u.username,
                    text='n%s-%s' % (i + 1, j + 1),
                    tags=['t%s' % (k + 1) for k in range(j)])

    def test_create(self):
        self.create_objects()
        self.assertEqual(
            sorted(user.username for user in User.all()),
            ['u1', 'u2', 'u3'])

        notes = Note.query(Note.user == 'u1')
        self.assertEqual(
            sorted(note.text for note in notes),
            ['n1-1', 'n1-2', 'n1-3'])

        notes = sorted(
            Note.query(Note.user == 'u2'),
            key = lambda note: note._id)
        note = notes[2]
        self.assertEqual(note.tags, ['t1', 't2'])

    def test_exceptions(self):
        self.assertRaises(KeyError, User.load, 'charlie')
        User.create(username='charlie')
        user = User.load('charlie')
        self.assertEqual(user.username, 'charlie')

    def test_query(self):
        self.create_objects()
        notes = Note.query(Note.user == 'u2')
        self.assertEqual(
            sorted(note.text for note in notes),
            ['n2-1', 'n2-2', 'n2-3'])

        user = User.get(User.username == 'u3')
        self.assertEqual(user._data, {'username': 'u3'})

        self.assertRaises(ValueError, User.get, User.username == 'ux')

    def test_sorting(self):
        self.create_objects()
        all_notes = [
            'n1-1', 'n1-2', 'n1-3', 'n2-1', 'n2-2', 'n2-3', 'n3-1', 'n3-2',
            'n3-3']

        notes = Note.query(order_by=Note.text)
        self.assertEqual([note.text for note in notes], all_notes)

        notes = Note.query(order_by=Note.text.desc())
        self.assertEqual(
            [note.text for note in notes],
            all_notes[::-1])

        notes = Note.query(Note.user == 'u2', Note.text)
        self.assertEqual(
            [note.text for note in notes],
            ['n2-1', 'n2-2', 'n2-3'])

        notes = Note.query(Note.user == 'u2', Note.text.desc())
        self.assertEqual(
            [note.text for note in notes],
            ['n2-3', 'n2-2', 'n2-1'])

    def test_complex_query(self):
        usernames = ['charlie', 'huey', 'mickey', 'zaizee']
        for username in usernames:
            User.create(username=username)

        def assertUsers(expr, expected):
            users = User.query(expr)
            self.assertEqual(
                sorted(user.username for user in users),
                sorted(expected))

        assertUsers(User.username == 'charlie', ['charlie'])
        assertUsers(User.username != 'huey', ['charlie', 'mickey', 'zaizee'])
        assertUsers(
            ((User.username == 'charlie') | (User.username == 'mickey')),
            ['charlie', 'mickey'])
        assertUsers(
            (User.username == 'charlie') | (User.username != 'mickey'),
            ['charlie', 'huey', 'zaizee'])
        expr = (
            ((User.username != 'huey') & (User.username != 'zaizee')) |
            (User.username == 'charlie'))
        assertUsers(expr, ['charlie', 'mickey'])

    def test_scalar_query(self):
        """
        class Stat(BaseModel):
            key = AutoIncrementField()
            stat_type = ByteField(index=True)
            value = IntegerField(index=True)
        """
        data = [
            ('t1', 1),
            ('t1', 2),
            ('t1', 3),
            ('t2', 10),
            ('t2', 11),
            ('t2', 12),
            ('t3', 0),
        ]
        for stat_type, value in data:
            Stat.create(stat_type=stat_type, value=value)

        stat_objects = sorted(
            (stat for stat in Stat.all()),
            key=lambda stat: stat.key)
        self.assertEqual([stat._data for stat in stat_objects], [
            {'key': 1, 'stat_type': 't1', 'value': 1},
            {'key': 2, 'stat_type': 't1', 'value': 2},
            {'key': 3, 'stat_type': 't1', 'value': 3},
            {'key': 4, 'stat_type': 't2', 'value': 10},
            {'key': 5, 'stat_type': 't2', 'value': 11},
            {'key': 6, 'stat_type': 't2', 'value': 12},
            {'key': 7, 'stat_type': 't3', 'value': 0},
        ])

        def assertStats(expr, expected):
            stats = Stat.query(expr)
            self.assertEqual(
                sorted(stat.key for stat in stats),
                sorted(expected))

        assertStats(Stat.value <= 3, [1, 2, 3, 7])
        assertStats(Stat.value >= 10, [4, 5, 6])
        assertStats(Stat.value < 3, [1, 2, 7])
        assertStats(Stat.value > 10, [5, 6])

        assertStats(Stat.value == 3, [3])
        assertStats(Stat.value >= 13, [])
        assertStats(
            (Stat.value <= 2) | (Stat.key >= 7),
            [1, 2, 7])
        assertStats(
            ((Stat.value <= 2) & (Stat.key >= 7)) | (Stat.value >= 11),
            [5, 6, 7])
        assertStats(
            ((Stat.value <= 2) | (Stat.key >= 7)) & (Stat.stat_type == 't1'),
            [1, 2])

        assertStats(Stat.value.between(2, 11), [2, 3, 4, 5])
        assertStats(Stat.value.between(4, 12), [4, 5, 6])

    def test_full_text_search(self):
        phrases = [
            ('A faith is a necessity to a man. Woe to him who believes in '
             'nothing.'),
            ('All who call on God in true faith, earnestly from the heart, '
             'will certainly be heard, and will receive what they have asked '
             'and desired.'),
            ('Be faithful in small things because it is in them that your '
             'strength lies.'),
            ('Faith consists in believing when it is beyond the power of '
             'reason to believe.'),
            ('Faith has to do with things that are not seen and hope with '
             'things that are not at hand.')]

        for idx, message in enumerate(phrases):
            Message.create(content=message, status=1 + (idx % 2))

        def assertMatches(query, indexes):
            results = [message.content for message in query]
            self.assertEqual(results, [phrases[i] for i in indexes])

        def assertSearch(search, indexes):
            assertMatches(
                Message.query(Message.content.match(search)),
                indexes)

        assertSearch('faith', [4, 3, 2, 0, 1])
        assertSearch('faith man', [0])
        assertSearch('things', [4, 2])
        assertSearch('blah', [])

        query = Message.query(
            Message.content.match('faith') & (Message.status == 1))
        assertMatches(query, [4, 2, 0])

    def test_full_text_options(self):
        phrases = [
            'building web applications with python and flask',
            'modern web development with python',
            'unit testing with python',
            'writing better tests for your application',
            'applications for the web',
        ]

        for phrase in phrases:
            FTSOptions.create(content=phrase, metaphone=phrase)

        def assertMatches(search, indexes, use_metaphone=False):
            if use_metaphone:
                field = FTSOptions.metaphone
            else:
                field = FTSOptions.content
            query = FTSOptions.query(field.match(search))
            results = [message.content for message in query]
            self.assertEqual(results, [phrases[i] for i in indexes])

        assertMatches('web application', [4, 0])
        assertMatches('web application', [4, 0], True)

        assertMatches('python', [2, 1, 0])
        assertMatches('python', [2, 1, 0], True)

        assertMatches('testing', [3, 2])
        assertMatches('testing', [3, 2], True)

        # Test behavior of the metaphone algorithm.
        assertMatches('python flasck', [0], True)
        assertMatches('pithon devellepment', [], False)
        assertMatches('pithon devellepment', [1], True)
        assertMatches('younit tessts', [2], True)

    def test_fts_query_parser(self):
        messages = [
            'foo green',
            'bar green',
            'baz blue',
            'nug blue',
            'nize yellow',
            'huey greener',
            'mickey greens',
            'zaizee',
        ]
        for message in messages:
            Message.create(content=message)

        def assertMatches(query, expected, default_conjunction=OP_AND):
            expression = Message.content.search(query, default_conjunction)
            messages = Message.query(expression, order_by=Message.content)
            results = [msg.content for msg in messages]
            self.assertEqual(results, expected)

        assertMatches('foo', ['foo green'])
        assertMatches('foo OR baz', ['baz blue', 'foo green'])
        assertMatches('green OR blue', [
            'bar green',
            'baz blue',
            'foo green',
            'mickey greens',
            'nug blue',
        ])
        assertMatches('green AND (bar OR mickey OR nize)', [
            'bar green',
            'mickey greens',
        ])
        assertMatches('zaizee OR (blue AND nug) OR (green AND bar)', [
            'bar green',
            'nug blue',
            'zaizee',
        ])
        assertMatches('(blue AND (baz OR (nug OR huey OR mickey))', [
            'baz blue',
            'nug blue',
        ])
        assertMatches(
            '(blue OR foo) AND (green OR (huey OR (baz AND mickey)))',
            ['foo green'])

        assertMatches('(green AND nug) OR (blue AND bar)', [])
        assertMatches('nuglet', [])
        assertMatches('foobar', [])
        assertMatches('', sorted(messages))

    def test_load(self):
        User.create(username='charlie')
        u = User.load('charlie')
        self.assertEqual(u._data, {'username': 'charlie'})

    def test_save_delete(self):
        charlie = User.create(username='charlie')
        huey = User.create(username='huey')
        note = Note.create(user='huey', text='n1')
        note.text = 'n1-edited'
        note.save()

        self.assertEqual(
            sorted(user.username for user in User.all()),
            ['charlie', 'huey'])

        notes = Note.all()
        self.assertEqual([note.text for note in notes], ['n1-edited'])

        charlie.delete()
        self.assertEqual([user.username for user in User.all()], ['huey'])

    def test_delete_indexes(self):
        self.assertEqual(set(db.keys()), set())

        Message.create(content='charlie message', status=1)
        Message.create(content='huey message', status=2)

        keys = set(db.keys())
        charlie = Message.load(1)
        charlie.delete()

        huey_keys = set(db.keys())
        diff = keys - huey_keys

        make_key = Message._query.make_key
        self.assertEqual(diff, set([
            make_key('_id', 'absolute', 1),
            make_key('content', 'absolute', 'charlie message'),
            make_key('content', 'fts', 'charli'),
            make_key('id', 1),
            make_key('status', 'absolute', 1),
        ]))

        # Ensure we cannot query for Charlie, but that we can query for Huey.
        expressions = [
            (Message.status == 1),
            (Message.status != 2),
            (Message._id == 1),
            (Message._id != 2),
            (Message.content == 'charlie message'),
            (Message.content != 'huey message'),
            (Message.content.match('charlie')),
        ]
        for expression in expressions:
            self.assertRaises(ValueError, Message.get, expression)

        expressions = [
            (Message.status == 2),
            (Message.status > 1),
            (Message._id == 2),
            (Message._id != 1),
            (Message.content == 'huey message'),
            (Message.content != 'charlie'),
            (Message.content.match('huey')),
            (Message.content.match('message')),
        ]
        for expression in expressions:
            obj = Message.get(expression)
            self.assertEqual(obj._data, {
                '_id': 2,
                'content': 'huey message',
                'status': 2,
            })

        after_filter_keys = set(db.keys())
        symm_diff = huey_keys ^ after_filter_keys
        self.assertTrue(all(key.startswith('temp') for key in symm_diff))

        huey = Message.load(2)
        huey.delete()

        final_keys = set(key for key in db.keys()
                         if not key.startswith('temp'))
        self.assertEqual(final_keys, set([make_key('_id', '_sequence')]))

    def test_get_regression(self):
        Message.create(content='huey', status=1)
        Message.create(content='charlie', status=2)

        def assertMessage(msg, data):
            self.assertEqual(msg._data, data)

        huey = {'_id': 1, 'content': 'huey', 'status': 1}
        charlie = {'_id': 2, 'content': 'charlie', 'status': 2}
        assertMessage(Message.load(1), huey)
        assertMessage(Message.load(2), charlie)

        for i in range(3):
            assertMessage(Message.get(Message._id == 1), huey)
            assertMessage(Message.get(Message._id == 2), charlie)

            assertMessage(Message.get(Message.status == 1), huey)
            assertMessage(Message.get(Message.status == 2), charlie)
            assertMessage(Message.get(Message.status != 1), charlie)
            assertMessage(Message.get(Message.status != 2), huey)

            messages = list(Message.query(Message.status == 1))
            self.assertEqual(len(messages), 1)
            assertMessage(messages[0], huey)
            messages = list(Message.query(Message.status != 1))
            self.assertEqual(len(messages), 1)
            assertMessage(messages[0], charlie)


class TestCache(WalrusTestCase):
    def test_cache_apis(self):
        self.assertEqual(cache.get('foo'), None)
        cache.set('foo', 'bar', 60)
        self.assertEqual(cache.get('foo'), 'bar')
        cache.delete('foo')
        self.assertEqual(cache.get('foo'), None)

    def test_cache_decorator(self):
        n1 = now()
        n2 = now(1)
        self.assertNotEqual(n1, n2)
        self.assertEqual(now(), n1)
        self.assertEqual(now(1), n2)

        now.bust(1)
        self.assertNotEqual(now(1), n2)
        self.assertEqual(now(1), now(1))


class TestHash(WalrusTestCase):
    def setUp(self):
        super(TestHash, self).setUp()
        self.hsh = db.Hash('my-hash')

    def test_item_api(self):
        self.hsh['k1'] = 'v1'
        self.assertEqual(self.hsh['k1'], 'v1')
        self.assertEqual(self.hsh['kx'], None)

        self.hsh['k2'] = 'v2'
        self.hsh['k3'] = 'v3'
        self.assertEqual(self.hsh.as_dict(), {
            'k1': 'v1',
            'k2': 'v2',
            'k3': 'v3'})

        del self.hsh['k2']
        self.assertEqual(self.hsh.as_dict(), {'k1': 'v1', 'k3': 'v3'})

    def test_dict_apis(self):
        self.hsh.update({'k1': 'v1', 'k2': 'v2'})
        self.hsh.update(k3='v3', k4='v4')
        self.assertEqual(sorted(self.hsh.items()), [
            ('k1', 'v1'),
            ('k2', 'v2'),
            ('k3', 'v3'),
            ('k4', 'v4')])
        self.assertEqual(sorted(self.hsh.keys()), ['k1', 'k2', 'k3', 'k4'])
        self.assertEqual(sorted(self.hsh.values()), ['v1', 'v2', 'v3', 'v4'])

        self.assertEqual(len(self.hsh), 4)
        self.assertTrue('k1' in self.hsh)
        self.assertFalse('kx' in self.hsh)

    def test_search_iter(self):
        self.hsh.update(foo='v1', bar='v2', baz='v3')
        self.assertEqual(sorted(self.hsh), [
            ('bar', 'v2'),
            ('baz', 'v3'),
            ('foo', 'v1'),
        ])
        self.assertEqual(sorted(self.hsh.search('b*')), [
            ('bar', 'v2'),
            ('baz', 'v3'),
        ])


class TestSet(WalrusTestCase):
    def setUp(self):
        super(TestSet, self).setUp()
        self.set = db.Set('my-set')

    def assertSet(self, expected):
        self.assertEqual(self.set.members(), set(expected))

    def test_basic_apis(self):
        self.set.add('i1', 'i2', 'i3', 'i2', 'i1')
        self.assertSet(['i1', 'i2', 'i3'])

        self.set.remove('i2')
        self.assertSet(['i1', 'i3'])

        self.set.remove('ix')
        self.assertSet(['i1', 'i3'])

        # Test __contains__
        self.assertTrue('i1' in self.set)
        self.assertFalse('ix' in self.set)

        # Test __iter__.
        self.assertEqual(sorted(self.set), ['i1', 'i3'])

        del self.set['i3']
        self.assertSet(['i1'])

    def test_combining(self):
        self.set2 = db.Set('my-set2')
        self.set.add(1, 2, 3, 4)
        self.set2.add(3, 4, 5, 6)

        self.assertEqual(
            self.set | self.set2,
            set(['1', '2', '3', '4', '5', '6']))

        self.assertEqual(
            self.set & self.set2,
            set(['3', '4']))

        self.assertEqual(
            self.set - self.set2,
            set(['1', '2']))
        self.assertEqual(
            self.set2 - self.set,
            set(['5', '6']))

    def test_combine_store(self):
        self.set2 = db.Set('my-set2')
        self.set.add(1, 2, 3, 4)
        self.set2.add(3, 4, 5, 6)

        s3 = self.set.unionstore('my-set3', self.set2)
        self.assertEqual(s3.members(), set(['1', '2', '3', '4', '5', '6']))

        s3 = self.set.interstore('my-set3', self.set2)
        self.assertEqual(s3.members(), set(['3', '4']))

        s3 = self.set.diffstore('my-set3', self.set2)
        self.assertEqual(s3.members(), set(['1', '2']))

        self.set |= self.set2
        self.assertSet(['1', '2', '3', '4', '5', '6'])

        s4 = db.Set('my-set4')
        s4.add('1', '3')
        s3 &= s4
        self.assertEqual(s3.members(), set(['1']))

    def test_search(self):
        self.set.add('foo', 'bar', 'baz', 'nug')
        self.assertEqual(sorted(self.set.search('b*')), ['bar', 'baz'])


class TestZSet(WalrusTestCase):
    def setUp(self):
        super(TestZSet, self).setUp()
        self.zs = db.ZSet('my-zset')

    def assertZSet(self, expected):
        self.assertEqual(list(self.zs), expected)

    def test_basic_apis(self):
        self.zs.add('i1', 1, 'i2', 2)
        self.assertZSet([('i1', 1), ('i2', 2)])

        self.zs.add('i0', 0)
        self.zs.add('i3', 3)
        self.assertZSet([('i0', 0), ('i1', 1), ('i2', 2), ('i3', 3)])

        self.zs.remove('i1')
        self.zs.remove_by_score(3)
        self.zs.add('i2', -2)
        self.zs.add('i9', 9)
        self.assertZSet([('i2', -2.), ('i0', 0.), ('i9', 9.)])

        # __len__
        self.assertEqual(len(self.zs), 3)

        # __contains__
        self.assertTrue('i0' in self.zs)
        self.assertFalse('i1' in self.zs)

        self.assertEqual(self.zs.score('i2'), -2)
        self.assertEqual(self.zs.score('ix'), None)

        self.assertEqual(self.zs.rank('i0'), 1)
        self.assertEqual(self.zs.rank('i1'), None)

        self.assertEqual(self.zs.count(0, 10), 2)
        self.assertEqual(self.zs.count(-3, 11), 3)

        self.zs.incr('i2')
        self.zs.incr('i0', -2)
        self.assertZSet([('i0', -2.), ('i2', -1.), ('i9', 9.)])

        self.assertEqual(self.zs.range_by_score(0, 9), ['i9'])
        self.assertEqual(self.zs.range_by_score(-3, 0), ['i0', 'i2'])

    def test_item_apis(self):
        self.zs['i1'] = 1
        self.zs['i0'] = 0
        self.zs['i3'] = 3
        self.zs['i2'] = 2

        self.assertEqual(self.zs[0, False], ['i0'])
        self.assertEqual(self.zs[0, True], [('i0', 0)])
        self.assertEqual(self.zs[2, False], ['i2'])
        self.assertEqual(self.zs[2, True], [('i2', 2)])
        self.assertEqual(self.zs[-1, True], [('i3', 3)])
        self.assertEqual(self.zs[9, True], [])

        self.assertEqual(self.zs[0], ['i0'])
        self.assertEqual(self.zs[2], ['i2'])
        self.assertEqual(self.zs[9], [])

        del self.zs['i1']
        del self.zs['i3']
        self.zs['i2'] = -2
        self.zs['i9'] = 9
        self.assertZSet([('i2', -2.), ('i0', 0.), ('i9', 9.)])

    def test_slicing(self):
        self.zs.add('i1', 1, 'i2', 2, 'i3', 3, 'i0', 0)
        self.assertEqual(self.zs[:1, True], [('i0', 0)])
        self.assertEqual(self.zs[1:3, False], ['i1', 'i2'])
        self.assertEqual(self.zs[1:-1, True], [('i1', 1), ('i2', 2)])

        self.assertEqual(self.zs['i1':, False], ['i1', 'i2', 'i3'])
        self.assertEqual(self.zs[:'i2', False], ['i0', 'i1'])
        self.assertEqual(
            self.zs['i0':'i3', True],
            [('i0', 0), ('i1', 1), ('i2', 2)])
        self.assertRaises(KeyError, self.zs.__getitem__, (slice('i9'), False))
        self.assertEqual(self.zs[99:, False], [])

        del self.zs[:'i2']
        self.assertZSet([('i2', 2.), ('i3', 3.)])
        del self.zs[1:]
        self.assertZSet([('i2', 2.)])

    def test_combine_store(self):
        zs2 = db.ZSet('my-zset2')
        self.zs.add(1, 1, 2, 2, 3, 3)
        zs2.add(3, 3, 4, 4, 5, 5)

        zs3 = self.zs.unionstore('my-zset3', zs2)
        self.assertEqual(
            list(zs3),
            [('1', 1.), ('2', 2.), ('4', 4.), ('5', 5.), ('3', 6.)])

        zs3 = self.zs.interstore('my-zset3', zs2)
        self.assertEqual(list(zs3), [('3', 6.)])

        self.zs |= zs2
        self.assertZSet([
            ('1', 1.), ('2', 2.), ('4', 4.), ('5', 5.), ('3', 6.)])

        zs3 &= zs2
        self.assertEqual(list(zs3), [('3', 9.)])

    def test_search(self):
        self.zs.add('foo', 1, 'bar', 2, 'baz', 1, 'nug', 3)
        self.assertEqual(
            list(self.zs.search('b*')),
            [('baz', 1.), ('bar', 2.)])


class TestList(WalrusTestCase):
    def setUp(self):
        super(TestList, self).setUp()
        self.lst = db.List('my-list')

    def assertList(self, expected):
        self.assertEqual(list(self.lst), expected)

    def test_basic_apis(self):
        self.lst.append('i1')
        self.lst.extend(['i2', 'i3'])
        self.lst.prepend('ix')
        self.assertList(['ix', 'i1', 'i2', 'i3'])

        self.lst.insert('iy', 'i2', 'before')
        self.lst.insert('iz', 'i2', 'after')
        self.assertList(['ix', 'i1', 'iy', 'i2', 'iz', 'i3'])

        self.assertEqual(self.lst.pop(), 'i3')
        self.assertEqual(self.lst.popleft(), 'ix')
        self.assertEqual(len(self.lst), 4)

    def test_item_apis(self):
        self.lst.append('i0')
        self.assertEqual(self.lst[0], 'i0')

        self.lst.extend(['i1', 'i2'])
        del self.lst['i1']
        self.assertList(['i0', 'i2'])

        self.lst[1] = 'i2x'
        self.assertList(['i0', 'i2x'])

        del self.lst[0]
        self.assertList(['i2x'])

        del self.lst[99]
        self.assertList(['i2x'])

        del self.lst['ixxx']
        self.assertList(['i2x'])

    def test_slicing(self):
        self.lst.extend(['i1', 'i2', 'i3', 'i4'])
        self.assertEqual(self.lst[:1], ['i1'])
        self.assertEqual(self.lst[:2], ['i1', 'i2'])
        self.assertEqual(self.lst[:-1], ['i1', 'i2', 'i3'])
        self.assertEqual(self.lst[1:2], ['i2'])
        self.assertEqual(self.lst[1:], ['i2', 'i3', 'i4'])

        l = db.List('l1')
        l.extend(range(10))
        del l[1:-1]
        self.assertEqual([int(i) for i in l], [1, 2, 3, 4, 5, 6, 7, 8, 9])

        del l[:3]
        self.assertEqual([int(i) for i in l], [1, 2, 3])


class TestArray(WalrusTestCase):
    def setUp(self):
        super(TestArray, self).setUp()
        self.arr = db.Array('my-arr')

    def test_basic_apis(self):
        self.arr.append('i1')
        self.arr.append('i2')
        self.arr.append('i3')
        self.arr.append('i4')
        self.assertEqual(len(self.arr), 4)

        # Indexing works. Invalid indices return None.
        self.assertEqual(self.arr[0], 'i1')
        self.assertEqual(self.arr[3], 'i4')
        self.assertEqual(self.arr[4], None)

        # Negative indexing works and includes bounds-checking.
        self.assertEqual(self.arr[-1], 'i4')
        self.assertEqual(self.arr[-4], 'i1')
        self.assertEqual(self.arr[-5], None)

        self.assertEqual(self.arr.pop(1), 'i2')
        self.assertEqual(list(self.arr), ['i1', 'i3', 'i4'])

        self.assertEqual(self.arr.pop(), 'i4')
        self.assertEqual(list(self.arr), ['i1', 'i3'])

        self.arr[-1] = 'iy'
        self.arr[0] = 'ix'
        self.assertEqual(list(self.arr), ['ix', 'iy'])

        self.assertTrue('iy' in self.arr)
        self.assertFalse('i1' in self.arr)

        self.arr.extend(['foo', 'bar', 'baz'])
        self.assertEqual(list(self.arr), ['ix', 'iy', 'foo', 'bar', 'baz'])


class TestWalrus(WalrusTestCase):
    def test_atomic(self):
        def assertDepth(depth):
            self.assertEqual(len(db._transaction_local.pipes), depth)

        assertDepth(0)
        with db.atomic() as p1:
            assertDepth(1)
            with db.atomic() as p2:
                assertDepth(2)
                with db.atomic() as p3:
                    assertDepth(3)
                    p3.pipe.set('k3', 'v3')

                assertDepth(2)
                self.assertEqual(db['k3'], 'v3')

                p2.pipe.set('k2', 'v2')

            assertDepth(1)
            self.assertEqual(db['k3'], 'v3')
            self.assertEqual(db['k2'], 'v2')
            p1.pipe.set('k1', 'v1')

        assertDepth(0)
        self.assertEqual(db['k1'], 'v1')
        self.assertEqual(db['k2'], 'v2')
        self.assertEqual(db['k3'], 'v3')

    def test_atomic_exception(self):
        def do_atomic(k, v, exc=False):
            with db.atomic() as a:
                a.pipe.set(k, v)
                if exc:
                    raise TypeError('foo')

        do_atomic('k', 'v')
        self.assertEqual(db['k'], 'v')

        self.assertRaises(TypeError, do_atomic, 'k2', 'v2', True)
        self.assertRaises(KeyError, lambda: db['k2'])
        self.assertEqual(db._transaction_local.pipe, None)

        # Try nested failure.
        with db.atomic() as outer:
            outer.pipe.set('k2', 'v2')
            self.assertRaises(TypeError, do_atomic, 'k3', 'v3', True)

            # Only this will be set.
            outer.pipe.set('k4', 'v4')

        self.assertEqual(db._transaction_local.pipe, None)
        self.assertEqual(db['k2'], 'v2')
        self.assertRaises(KeyError, lambda: db['k3'])
        self.assertEqual(db['k4'], 'v4')

    def test_clear_transaction(self):
        with db.atomic() as a1:
            a1.pipe.set('k1', 'v1')
            with db.atomic() as a2:
                a2.pipe.set('k2', 'v2')
                a2.clear()

        self.assertEqual(db['k1'], 'v1')
        self.assertRaises(KeyError, lambda: db['k2'])

        with db.atomic() as a1:
            a1.pipe.set('k3', 'v3')
            with db.atomic() as a2:
                self.assertRaises(KeyError, lambda: db['k3'])

                a2.pipe.set('k4', 'v4')
                a2.clear()

            a1.pipe.set('k5', 'v5')

        self.assertEqual(db['k3'], 'v3')
        self.assertRaises(KeyError, lambda: db['k4'])
        self.assertEqual(db['k5'], 'v5')

        self.assertEqual(db._transaction_local.pipe, None)


if __name__ == '__main__':
    unittest.main(argv=sys.argv)
