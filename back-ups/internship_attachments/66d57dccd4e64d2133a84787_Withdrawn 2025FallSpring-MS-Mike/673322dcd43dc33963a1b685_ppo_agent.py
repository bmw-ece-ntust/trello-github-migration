import os

import torch
import torch.nn as nn
import numpy as np
from torch.optim.adam import Adam

from .policy_network import PolicyNet
from .value_network import ValueNet


class PPOAgent:
    def __init__(self,
                 obs_dim: int,
                 action_dim: int,
                 max_step: int,
                 gamma: float = 0.99,
                 lamb: float = 0.95,
                 lr: float = 1e-4,
                 clip_val: float = 0.2,
                 max_grad_norm: float = 0.5,
                 ent_weight: float = 0.01,
                 sample_n_epoch: int = 4,
                 sample_mb_size: int = 64,
                 is_training: bool = True,
                 model_path: str = "./agent/weight.pth",
                 device: str = "cuda:0"
                 ) -> None:
        # Initialize hyperparameters
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.max_step = max_step
        self.gamma = gamma
        self.lamb = lamb
        self.lr = lr
        self.clip_val = clip_val
        self.max_grad_norm = max_grad_norm
        self.ent_weight = ent_weight
        self.sample_n_epoch = sample_n_epoch
        self.sample_mb_size = sample_mb_size
        self.is_training = is_training
        self.model_path = model_path
        # self.device = device
        # torch device可能會沒有GPU
        self.device = torch.device(device if "cuda" in device and torch.cuda.is_available() else "cpu")
        self.memory_counter = 0

        # Build networks
        self.policy_net = PolicyNet(self.obs_dim, self.action_dim).to(self.device)
        self.value_net = ValueNet(self.obs_dim).to(self.device)
        self.opt_policy = Adam(self.policy_net.parameters(), lr)
        self.opt_value = Adam(self.value_net.parameters(), lr)

        # Storage trajectory
        self.mb_obs = np.zeros((self.max_step, self.obs_dim), dtype=np.float32)
        self.mb_actions = np.zeros((self.max_step, self.action_dim), dtype=np.float32)
        self.mb_values = np.zeros((self.max_step,), dtype=np.float32)
        self.mb_rewards = np.zeros((self.max_step,), dtype=np.float32)
        self.mb_a_logps = np.zeros((self.max_step,), dtype=np.float32)

        if not self.is_training:
            self.load_model()

    def compute_discounted_return(self,
                                  rewards: np.ndarray,
                                  last_value: np.ndarray) -> np.ndarray:
        """
            Compute discounted return

            Args:
                rewards (np.ndarray) : 1D numpy array representing the sequence of rewards at each timestep.
                last_value (np.ndarray): The estimated value of the final state.

            Returns:
                returns (np.ndarray): 1D numpy array representing the discounted return for each timestep.
        """
        returns = np.zeros_like(rewards)
        n_step = len(rewards)

        # TODO: G_{n-1} = r_{n-1} + gamma * last_value
        # TODO: G_t = r_t + gamma * G_{t+1}
        pass

    def compute_gae(self,
                    rewards: np.ndarray,
                    values: np.ndarray,
                    last_value: np.ndarray) -> np.ndarray:
        """
        Compute the Generalized Advantage Estimation (GAE) for a trajectory.
        Args:
            rewards (np.ndarray): A 1D numpy array of rewards for each timestep.
            values (np.ndarray): A 1D numpy array of value estimates for each timestep.
            last_value (np.ndarray): The value estimate for the final state.

        Returns:
            np.ndarray: The advantage estimates plus the value function (returns) for each timestep.
        """

        advs = np.zeros_like(rewards)
        n_step = len(rewards)
        last_gae_lam = 0.0

        # TODO: delta_t = r_t + gamma * (V(s_{t+1}) - V(s_t))
        # TODO: adv_t = delta_t + gamma * lamb * adv_{t+1}
        pass

    @staticmethod
    def obs_preprocess(obs: dict) -> np.ndarray:
        """
        Get action based on observation

        Args:
            obs: dict
                `{'rgb_image': ndarray(128, 128, 3), 'lidar': ndarray(1080,), 'pose': ndarray(6,), 'velocity': ndarray(6,), 'acceleration': ndarray(6,)`

        Returns: np.ndarray
            agent observation input

        """

        # TODO Make your own observation preprocessing

        return np.concatenate([obs['pose'], obs['velocity'], obs['acceleration'], obs['lidar']], axis=-1)

    def get_action(self, obs: dict) -> tuple | dict[str:float, str:float]:
        """
            Get action based on observation

            Args:
                obs: dict
                    `{'rgb_image': ndarray(128, 128, 3), 'lidar': ndarray(1080,), 'pose': ndarray(6,), 'velocity': ndarray(6,), 'acceleration': ndarray(6,), time: ndarray(1,}`

            Returns: dict
                `{'motor': float,"steering": float}`
        """
        # TODO: Select action
        _obs = self.obs_preprocess(obs)
        _obs = torch.tensor(_obs, dtype=torch.float32).unsqueeze(0).to(self.device)

        with torch.no_grad():
            if self.is_training:
                action, a_logp = self.policy_net(_obs)
                value = self.value_net(_obs)

                action = action.cpu().detach().numpy()[0]
                a_logp = a_logp.cpu().detach().numpy()
                value = value.cpu().detach().numpy()

                return action, a_logp, value
            else:
                action, a_logp = self.policy_net(_obs)
                action = action.cpu().detach().numpy()[0]

                return {"motor": np.clip(action[0], -1, 1),
                        'steering': np.clip(action[1], -1, 1)}


    def learn(self) -> None:
        with torch.no_grad():
            # Compute last value
            last_obs = self.mb_obs[self.memory_counter]
            last_obs = torch.tensor(last_obs, dtype=torch.float32).unsqueeze(0).to(self.device)
            last_value = self.value_net(last_obs).cpu().detach().numpy()[0]

            # Compute returns
            mb_returns = self.compute_discounted_return(self.mb_rewards[:self.memory_counter - 1], last_value)

            # Sample from memory
            mb_obs = self.mb_obs[:self.memory_counter - 1]
            mb_actions = self.mb_actions[:self.memory_counter - 1]
            mb_a_logps = self.mb_a_logps[:self.memory_counter - 1]
            mb_values = self.mb_values[:self.memory_counter - 1]

            # Compute advantages
            mb_advs = mb_returns - mb_values
            mb_advs = (mb_advs - mb_advs.mean()) / (mb_advs.std() + 1e-6)

        # To tensor
        mb_obs = torch.from_numpy(mb_obs).to(self.device)
        mb_actions = torch.from_numpy(mb_actions).to(self.device)
        mb_old_values = torch.from_numpy(mb_a_logps).to(self.device)
        mb_advs = torch.from_numpy(mb_advs).to(self.device)
        mb_returns = torch.from_numpy(mb_returns).to(self.device)
        mb_old_a_logps = torch.from_numpy(mb_a_logps).to(self.device)

        # Compute minibatch size
        episode_length = len(mb_obs)
        rand_idx = np.arange(episode_length)
        sample_n_mb = episode_length // self.sample_mb_size

        if sample_n_mb <= 0:
            sample_mb_size = episode_length
            sample_n_mb = 1
        else:
            sample_mb_size = self.sample_mb_size

        # Training
        for i in range(self.sample_n_epoch):
            np.random.shuffle(rand_idx)

            for j in range(sample_n_mb):
                # Randomly sample a batch for training
                sample_idx = rand_idx[j * sample_mb_size: (j + 1) * sample_mb_size]
                sample_obs = mb_obs[sample_idx]
                sample_actions = mb_actions[sample_idx]
                sample_old_values = mb_old_values[sample_idx]
                sample_advs = mb_advs[sample_idx]
                sample_returns = mb_returns[sample_idx]
                sample_old_a_logps = mb_old_a_logps[sample_idx]

                # TODO: PPO algorithm


                # Train actor
                self.opt_policy.zero_grad()
                pg_loss.backward()
                nn.utils.clip_grad_norm_(self.policy_net.parameters(), self.max_grad_norm)
                self.opt_policy.step()

                # Train critic
                self.opt_value.zero_grad()
                v_loss.backward()
                nn.utils.clip_grad_norm_(self.value_net.parameters(), self.max_grad_norm)
                self.opt_value.step()

        self.memory_counter = 0

    def store_trajectory(self,
                         obs: dict,
                         action: np.ndarray,
                         value: np.ndarray,
                         a_logp: np.ndarray,
                         reward: float) -> None:
        """
            Store the trajectory (experience) during interaction with the environment.

            Args:
                obs (dict): Observation from the environment, which includes pose, velocity, acceleration, and lidar data.
                action (np.ndarray): The action taken by the agent at the current timestep.
                value (np.ndarray): The estimated value of the current state (from the value network).
                a_logp (np.ndarray): The log-probability of the action taken (from the policy network).
                reward (float): The reward received from the environment after taking the action.
        """

        _obs = self.obs_preprocess(obs)

        self.mb_obs[self.memory_counter] = _obs
        self.mb_actions[self.memory_counter] = action
        self.mb_values[self.memory_counter] = value
        self.mb_rewards[self.memory_counter] = reward
        self.mb_a_logps[self.memory_counter] = a_logp

        self.memory_counter += 1

    def save_model(self) -> None:
        """Save model"""
        torch.save(self.policy_net.state_dict(), self.model_path)

    def load_model(self) -> None:
        """Load model"""
        if os.path.exists(self.model_path) is False:
            print(f"Model path {self.model_path} does not exist")
            return

        print(f"Load model from {self.model_path}")
        self.policy_net.load_state_dict(torch.load(self.model_path))
