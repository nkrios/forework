import re
import json

from . import (utils, config)

logger = utils.get_logger(__name__)

PRIO_LOW = -10
PRIO_NORMAL = 0
PRIO_HIGH = 10

_tasks_cache = None


def find_tasks(name=None, rebuild_cache=False):
    '''
    Discover all the available tasks. If `name` is not None, it will search only
    tasks matching that name. If `rebuild_cache` is True, it will invalidate and
    rebuild the tasks cache even if task caching is enabled.
    If task caching is not enabled (see forework.config.ENABLE_TASKS_CACHE), the
    task list will be rebuilt at every call, which is very inefficient
    '''
    if config.ENABLE_TASKS_CACHE and not rebuild_cache:
        if _tasks_cache is None:
            logger.info('Tasks cache enabled but cache is empty. Performing '
                        'task search')
        else:
            return _tasks_cache
    logger.info('Searching for tasks in %r', config.tasks_dir)
    import importlib
    modules = importlib.__import__('forework.tasks', fromlist='*')
    tasks = []
    for modulename in dir(modules):
        if modulename[:2] == '__':
            continue
        module = importlib.import_module(
            'forework.tasks.{m}'.format(m=modulename),
        )
        classes = [o for o in dir(module) if o[:2] != '__']
        for classname in classes:
            if classname == name or name is None:
                cls = getattr(module, classname)
                if type(cls) == type and cls != BaseTask and \
                        issubclass(cls, BaseTask):
                    tasks.append(cls)
    if name is not None:
        assert len(tasks) in (0, 1), ('Found more than one task named {t!r}'
                                      .format(t=name))
    return tasks


def find_tasks_by_filetype(filetype, first_only=True):
    '''
    Search for tasks that can handle a file type (described as a string), and
    return their names as a list of strings. If `first_only` is True, only the
    first task name is returned, as a string.
    '''
    logger.info('Searching for tasks that can handle %r', filetype)
    all_tasks = find_tasks()
    suitable_tasks = []
    for task in all_tasks:
        if task.can_handle(filetype):
            if first_only:
                return task.__name__
            suitable_tasks.append(task.__name__)
    return suitable_tasks


class BaseTask:

    MAGIC_PATTERN = None
    _rx = None

    def __init__(self, path, priority=PRIO_NORMAL):
        self._name = self.__class__.__name__
        self._path = path
        self._done = False
        self._result = None
        self._priority = priority
        self._next_tasks = []

    def __repr__(self):
        return '<{cls}(result={r!r})>'.format(
            cls=self.__class__.__name__,
            r=self._result if self._done else '<unfinished>',
        )

    @classmethod
    def can_handle(self, magic_string):
        if self.MAGIC_PATTERN is None:
            raise Exception('MAGIC_PATTERN must be defined by the task {name}'
                            .format(name=self._name))
        if self._rx is None:
            self._rx = re.compile(self.MAGIC_PATTERN)
        return self._rx.match(magic_string)

    def to_json(self):
        '''
        Return a JSON representation of this task and its status.

        This method wraps around to_dict and should not be overridden.
        '''
        return json.dumps(self.to_dict())

    def to_dict(self):
        '''
        Return a dict representation of this task and its status.

        This method returns basic task information and should be overridden by
        derived tasks.
        Derived tasks can reuse the dict returned by this method and add or
        amend part of the information. They should never remove items though.
        All the items must be JSON-serializable.
        '''
        return {
            'name': self._name,
            'path': self._path,
            'completed': self._done,
            'priority': self._priority,
            'result': self.get_result(),
            'next_tasks': self.get_next_tasks(),

        }

    @staticmethod
    def from_json(taskjson):
        '''
        Build a task from its JSON representation (see `to_json`)
        '''
        return BaseTask.from_dict(json.loads(taskjson))

    @staticmethod
    def from_dict(taskdict):
        '''
        Build a task from its dict representation (see `to_dict`)
        '''
        cls = find_tasks(taskdict['name'])[0]
        path = taskdict['path']
        args = taskdict.get('args', [])
        task = cls(path, *args, priority=taskdict.get('priority', PRIO_NORMAL))
        task.done = taskdict.get('completed', False)
        task._result = taskdict.get('result', None)
        return task

    @property
    def done(self):
        return self._done

    @done.setter
    def done(self, value):
        if type(value) != bool:
            raise Exception(
                'Value for {cls}.done must be a boolean'
                .format(cls=self.__class__.__name__),
            )
        self._done = value

    def add_next_task(self, jsondata):
        '''
        Add a new follow-up task to the next_tasks list. The input is a valid
        JSON representation of a task.
        '''
        self._next_tasks.append(jsondata)

    def get_next_tasks(self):
        '''
        Return the list of tasks to do next. Every task is in JSON format.
        '''
        return [json.dumps(t) for t in self._next_tasks]

    def start(self):
        self._done = False
        self.run()
        self._done = True
        return self

    def run(self):
        # NOTE: when overriding, remember to call self.done(True) to indicate
        #       that a task has completed and can yield a result
        msg = ('Attempted to call virtual method `run`, this method must be '
               'overridden')
        logger.warning(msg)
        raise NotImplementedError(msg)

    def get_result(self):
        if self.done:
            return self._result
        msg = 'Attempted to get results on a task that is still running'
        logger.warning(msg)
        return None
