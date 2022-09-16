import numpy as np
from gym.spaces import Box
from gym import ObservationWrapper
from gym.wrappers import TimeLimit


class MyTimeAwareObservation(ObservationWrapper):
    r"""Augment the observation with current time step in the trajectory.

    .. note::
        Currently it only works with one-dimensional observation space. It doesn't
        support pixel observation space yet.

    """

    def __init__(self, env: TimeLimit):
        super(MyTimeAwareObservation, self).__init__(env)
        print(env)
        assert isinstance(env, TimeLimit)
        assert isinstance(env.observation_space, Box)
        assert env.observation_space.dtype == np.float32
        low = np.append(self.observation_space.low, -1.)
        high = np.append(self.observation_space.high, 1.)
        self.observation_space = Box(low, high, dtype=np.float32)
        self.env = env

    def normalize(self, x, low, high):
        return 2 * (x - low) / (high - low) - 1

    def observation(self, observation):
        return np.append(observation, self.normalize(self.env._elapsed_steps, 0, self.env._max_episode_steps))

    # def step(self, action):
    #     self.t += 1
    #     return super(MyTimeAwareObservation, self).step(action)

    # def reset(self, **kwargs):
    #     self.t = 0
    #     return super(MyTimeAwareObservation, self).reset(**kwargs)
