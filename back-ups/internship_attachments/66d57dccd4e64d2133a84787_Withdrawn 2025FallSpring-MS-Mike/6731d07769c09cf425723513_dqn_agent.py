import os

import torch
import torch.nn as nn
import numpy as np
from torch.optim.adam import Adam

from .dqn_network import DQNNetwork
from .replay_buffer import ReplayBuffer


class DQNAgent:
    def __init__(self,
                 state_dim: int,
                 lr: float = 1e-4,
                 gamma: float = 0.99,
                 epsilon: float = 1.0,
                 epsilon_decay: float = 0.999,
                 epsilon_min: float = 0.01,
                 memory_size: int = 10000,
                 batch_size: int = 32,
                 target_update: int = 100,
                 is_training: bool = True,
                 model_path: str = "./agent/weight.pth",
                 device: str = "cuda:0") -> None:
        """
        state_dim (int): dimension of state
        lr (float): learning rate
        gamma (float): discount factor
        epsilon (float): epsilon for e-greedy
        epsilon_decay (float): decay rate of epsilon
        epsilon_min (float): minimum epsilon
        memory_size (int): size of replay buffer
        batch_size (int): size of batch
        target_update (int): update frequency of target network
        is_training (bool): if True, use epsilon-greedy
        model_path (str): path to save model
        device (str): which device to use, e.g. "cpu" or "cuda:0"
        """

        # Initialize hyperparameters
        self.state_dim = state_dim
        self.action_map = self.generate_action_map()
        self.action_dim = len(self.action_map)
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.epsilon_min = epsilon_min
        self.batch_size = batch_size
        self.learn_step_counter = 0
        self.target_update = target_update
        self.is_training = is_training
        self.model_path = model_path
        # self.device = device
        # torch device可能會沒有GPU
        self.device = torch.device(device if "cuda" in device and torch.cuda.is_available() else "cpu")

        # Build memory
        self.memory = ReplayBuffer(memory_size, state_dim)

        # Build networks
        self.qnet_eval = DQNNetwork(state_dim, self.action_dim).to(self.device)
        self.qnet_target = DQNNetwork(state_dim, self.action_dim).to(self.device)
        self.qnet_target.eval()
        self.optimizer = Adam(self.qnet_eval.parameters(), lr=self.lr)
        self.loss_fn = nn.SmoothL1Loss()
        self.update_target_network()

        # Load weight
        if not self.is_training:
            self.load_model()

    @staticmethod
    def generate_action_map() -> list[dict[str, float]]:    #將連續的(動作)action space轉換成離散的(動作)action space
        """
        Because the action space is continuous, we need to generate a discrete action space
        to map the continuous action space to discrete action space

        Return:
            action_map (list[dict[str, float]]): list of action map
        """
        motor = np.linspace(-1, 1.0, 10)               #馬達的動作範圍
        steering = np.linspace(-1.0, 1.0, 10)          #方向盤的動作範圍

        action_map = []
        for m in motor:
            for s in steering:
                action_map.append({"motor": m, "steering": s})

        return action_map

    @staticmethod
    def obs_preprocess(obs: dict) -> np.ndarray:
        """
        Get action based on observation

        Args:
            obs: dict
                {'rgb_image': ndarray(128, 128, 3), 'lidar': ndarray(1080,), 'pose': ndarray(6,), 'velocity': ndarray(6,), 'acceleration': ndarray(6,)

        Returns: np.ndarray
            agent observation input

        """

        # TODO Make your own observation preprocessing

        return np.concatenate([obs['pose'], obs['velocity'], obs['acceleration'], obs['lidar']], axis=-1)

    def get_action(self, obs: dict) -> dict[str, float]:       #取得動作(e-greedy)  
        """
        Get action based on observation

        Args:
            obs: dict
                {'rgb_image': ndarray(128, 128, 3), 'lidar': ndarray(1080,), 'pose': ndarray(6,), 'velocity': ndarray(6,), 'acceleration': ndarray(6,), time: ndarray(1,}

        Returns: dict
            {'motor': float,"steering": float}

        """
        # TODO: Select action
        _obs = self.obs_preprocess(obs)
        _obs = torch.tensor(_obs).float().unsqueeze(0).to(self.device)

        with torch.no_grad():
            #if training, use epsilon-greedy
            if self.is_training and np.random.random() < self.epsilon:    #動作選擇
                action_idx = np.random.randint(0, self.action_dim)
            else:
                action_idx = self.qnet_eval(_obs).argmax().item()   #選擇最大的Q值

        return self.action_map[action_idx]
    

    def store_transition(self,
                         obs: dict,
                         action: dict[str, float],
                         reward: float | int,
                         next_obs: dict,
                         done: bool) -> None:
        """
        Store transition in memory
        Args:
            obs (dict): current state
            action (dict[str, float]): action
            reward (float | int): reward
            next_obs (dict): next state
            done (bool): done
        """
        _obs = self.obs_preprocess(obs)
        _next_obs = self.obs_preprocess(next_obs)
        action_idx = self.action_map.index(action)

        self.memory.store_transition(_obs, action_idx, reward, _next_obs, done)

    def learn(self) -> None:
        """
        Learn from experiences
        """
        if self.memory.mem_counter < self.batch_size:
            return

        # Sample batch experiences from memory
        batch_obs, batch_action, batch_reward, batch_next_obs, batch_done = \
            self.memory.sample_buffer(self.batch_size)

        batch_obs = torch.tensor(batch_obs, dtype=torch.float32).to(self.device)
        batch_action = torch.tensor(batch_action, dtype=torch.long).to(self.device)
        batch_reward = torch.tensor(batch_reward, dtype=torch.float32).to(self.device)
        batch_done = torch.tensor(batch_done, dtype=torch.float32).to(self.device)
        batch_next_obs = torch.tensor(batch_next_obs, dtype=torch.float32).to(self.device)

        # TODO: DQN Algorithm, formula: Q(s, a) = r + gamma * max_a' Q(s', a')
        #Q-learning algorithm
        q_eval = self.quet_eval(batch_action)
        q_eval = q_eval.gather(1, batch_action)

        q_next = self.qnet_target(batch_next_obs).detach()
        max_q_next = q_next.max(1)[0].view(-1,1)

        q_target = batch_reward + self.gamma * max_q_next * (1 - batch_done)

        #update eval network
        loss = self.loss_fn(q_eval, q_target)

        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        self.learn_step_counter += 1

        # Update target network and epsilon
        self.update_target_network()
        self.epsilon = max(self.epsilon * self.epsilon_decay, self.epsilon_min)

    def update_target_network(self) -> None:
        """Update target network's weights and epsilon"""
        if self.learn_step_counter % self.target_update != 0:
            return

        self.qnet_target.load_state_dict(self.qnet_eval.state_dict())

    def load_model(self) -> None:
        """Load model"""
        if os.path.exists(self.model_path) is False:
            print(f"Model path {self.model_path} does not exist")
            return

        print(f"Load model from {self.model_path}")
        self.qnet_eval.load_state_dict(torch.load(self.model_path))
        self.qnet_target.load_state_dict(torch.load(self.model_path))

    def save_model(self) -> None:
        """Save model"""
        torch.save(self.qnet_eval.state_dict(), self.model_path)