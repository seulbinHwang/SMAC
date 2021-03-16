import torch.nn as nn
import torch.nn.functional as F

import torch as th
from torch.distributions import Categorical


class DotSelector(nn.Module):
    def __init__(self, input_shape, args):
        super(DotSelector, self).__init__()
        self.args = args
        self.epsilon_start = self.args.epsilon_start
        self.epsilon_finish = self.args.role_epsilon_finish
        self.epsilon_anneal_time = self.args.epsilon_anneal_time
        self.epsilon_anneal_time_exp = self.args.epsilon_anneal_time_exp
        self.delta = (self.epsilon_start - self.epsilon_finish) / self.epsilon_anneal_time
        self.role_action_spaces_update_start = self.args.role_action_spaces_update_start
        self.epsilon_start_t = 0
        self.epsilon_reset = True

        self.fc1 = nn.Linear(args.rnn_hidden_dim, 2 * args.rnn_hidden_dim)
        self.fc2 = nn.Linear(2 * args.rnn_hidden_dim, args.action_latent_dim)

        self.epsilon = 0.05

    def forward(self, inputs, role_latent):
        x = self.fc2(F.relu(self.fc1(inputs)))  # [bs, action_dim] [n_roles, action_dim] (bs may be bs*n_agents)
        x = x.unsqueeze(-1)
        role_latent_reshaped = role_latent.unsqueeze(0).repeat(x.shape[0], 1, 1)

        role_q = th.bmm(role_latent_reshaped, x).squeeze()
        return role_q

    def select_role(self, role_qs, hp, test_mode=False, t_env=None):
        alpha = 0.7
        self.epsilon = self.epsilon_schedule(t_env)

        role_qs = F.softmax(role_qs)
        human_roleQ = self.calc_roleQ_by_human(hp)

        if test_mode:
            # Greedy action selection only
            self.epsilon = 0.0
            role_qs = alpha * role_qs + human_roleQ * (1 - alpha)

        # mask actions that are excluded from selection
        masked_q_values = role_qs.detach().clone()

        random_numbers = th.rand_like(role_qs[:, 0])
        pick_random = (random_numbers < self.epsilon).long()
        random_roles = Categorical(th.ones(role_qs.shape).float().to(self.args.device)).sample().long()

        picked_roles = pick_random * random_roles + (1 - pick_random) * masked_q_values.max(dim=1)[1]
        # [bs, 1]
        return picked_roles

    def calc_roleQ_by_human(self, hp):
        human_roleQ = []
        for index1 in range(len(hp)):
            for index2 in range(len(hp[index1])):
                cur_hp = hp[index1, index2]

                if cur_hp >= 0.7:
                    human_roleQ.append(th.FloatTensor([0.1, 0.2, 0.7]))
                elif cur_hp < 0.7 and cur_hp >= 0.2:
                    human_roleQ.append(th.FloatTensor([0.4, 0.4, 0.2]))
                else:
                    human_roleQ.append(th.FloatTensor([0.333333, 0.333333, 0.333333]))

        human_roleQ = th.stack(human_roleQ, dim=0)

        return human_roleQ


    def epsilon_schedule(self, t_env):
        if t_env is None:
            return 0.05

        if t_env > self.role_action_spaces_update_start and self.epsilon_reset:
            self.epsilon_reset = False
            self.epsilon_start_t = t_env
            self.epsilon_anneal_time = self.epsilon_anneal_time_exp
            self.delta = (self.epsilon_start - self.epsilon_finish) / self.epsilon_anneal_time

        if t_env - self.epsilon_start_t > self.epsilon_anneal_time:
            epsilon = self.epsilon_finish
        else:
            epsilon = self.epsilon_start - (t_env - self.epsilon_start_t) * self.delta

        return epsilon
