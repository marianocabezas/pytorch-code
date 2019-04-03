from itertools import product
import torch
import torch.nn.functional as F


def normalised_xcor(var_x, var_y):
    """
        Function that computes the normalised cross correlation between two
         tensors.
        :param var_x: First tensor.
        :param var_y: Second tensor.
        :return: A tensor with the normalised cross correlation
    """
    # Init
    var_x_flat = var_x.view(-1)
    var_y_flat = var_y.view(-1)
    if len(var_x_flat) > 1 and len(var_y_flat) > 1:
        # Computation
        var_x_norm = var_x - torch.mean(var_x_flat)
        var_y_norm = var_y - torch.mean(var_y_flat)
        var_xy_norm = torch.abs(torch.sum(var_x_norm * var_y_norm))
        inv_var_x_den = torch.rsqrt(torch.sum(var_x_norm * var_x_norm))
        inv_var_y_den = torch.rsqrt(torch.sum(var_y_norm * var_y_norm))

        return var_xy_norm * inv_var_x_den * inv_var_y_den
    else:
        return torch.mean(torch.abs(var_x - var_y))


def torch_entropy(var_x, var_y=None, bins=100):
    """
        Function that computes the entropy of a tensor or the joint entropy
         of two tensors using their histogram.
        :param var_x: First tensor.
        :param var_y: Second tensor (optional).
        :param bins: Number of bins for the histogram.
        :return: A tensor with the histogram
    """
    if var_y is None:
        h = torch_hist(var_x, bins=bins)
    else:
        h = torch_hist2(var_x, var_y, bins=bins)
    h = h[h > 0]
    return -torch.sum(h * torch.log(h))


def normalised_mutual_information(var_x, var_y):
    """
        Function that computes the normalised mutual information between two
         tensors, based on their histograms.
        :param var_x: First tensor.
        :param var_y: Second tensor.
        :return: A tensor with the normalised cross correlation
    """
    if len(var_x) > 1 and len(var_y) > 1:
        entr_x = torch_entropy(var_x)
        entr_y = torch_entropy(var_y)
        entr_xy = torch_entropy(var_x, var_y)
        return (entr_x + entr_y - entr_xy) / entr_x
    else:
        return torch.mean(torch.abs(var_x - var_y))


def normalised_xcor_loss(var_x, var_y):
    """
        Loss function based on the normalised cross correlation between two
         tensors. Since we are using gradient descent, the final value is
         1 - the normalised cross correlation.
        :param var_x: First tensor.
        :param var_y: Second tensor.
        :return: A tensor with the loss
    """
    if len(var_x) > 0 and len(var_y) > 0:
        return 1 - normalised_xcor(var_x, var_y)
    else:
        return torch.tensor(0)


def normalised_mi_loss(var_x, var_y):
    """
        Loss function based on the normalised mutual information between two
         tensors. Since we are using gradient descent, the final value is
         1 - the normalised cross correlation.
        :param var_x: First tensor.
        :param var_y: Second tensor.
        :return: A tensor with the loss
    """
    if len(var_x) > 0 and len(var_y) > 0:
        return 1 - normalised_mutual_information(var_x, var_y)
    else:
        return torch.tensor(0)


def subtraction_loss(var_x, var_y, mask):
    """
        Loss function based on the mean gradient of the subtraction between two
        tensors.
        :param var_x: First tensor.
        :param var_y: Second tensor.
        :param mask: Mask that defines the region of interest where the loss
         should be evaluated.
        :return: A tensor with the loss
    """
    return gradient_mean(var_y - var_x, mask)


def weighted_subtraction_loss(var_x, var_y, mask):
    """
        Loss function based on the mean gradient of the subtraction between two
        tensors weighted by the mask voxels.
        :param var_x: First tensor.
        :param var_y: Second tensor.
        :param mask: Mask that defines the region of interest where the loss
         should be evaluated.
        :return: A tensor with the loss
    """
    weight = torch.sum(mask.type(torch.float32)) / var_y.numel()
    return weight * gradient_mean(var_y - var_x, mask)


def df_loss(df, mask):
    """
        Loss function based on mean gradient of a deformation field.
        :param df: A deformation field tensor.
        :param mask: Mask that defines the region of interest where the loss
         should be evaluated.
        :return: A tensor with the loss
    """
    return gradient_mean(df, mask)


def mahalanobis_loss(var_x, var_y):
    """
        Loss function based on the Mahalanobis distance. this distance is
         computed between points and distributions, Therefore, we compute
         the distance between the mean of a distribution and the other
         distribution. To a guarantee that both standard deviations are taken
         into account, we compute a bidirectional loss (from one mean to the
         other distribution and viceversa).
        :param var_x: Predicted values.
        :param var_y: Expected values.
        :return: A tensor with the loss
    """
    # Init
    var_x_flat = var_x.view(-1)
    var_y_flat = var_y.view(-1)
    # Computation
    mu_x = torch.mean(var_x_flat)
    sigma_x = torch.std(var_x_flat)

    mu_y = torch.mean(var_y_flat)
    sigma_y = torch.std(var_y_flat)

    mu_diff = torch.abs(mu_x - mu_y)

    mahal = (sigma_x + sigma_y) * mu_diff

    return mahal / (sigma_x * sigma_y) if (sigma_x * sigma_y) > 0 else mahal


def torch_hist(var_x, bins=100, norm=True):
    """
        Function that computes a histogram using a torch tensor.
        :param var_x: Input tensor.
        :param bins: Number of bins for the histogram.
        :param norm: Whether or not to normalise the histogram. It is useful
        to define a probability density function of a given variable.
        :return: A tensor with the histogram
    """
    min_x = torch.floor(torch.min(var_x)).data
    max_x = torch.ceil(torch.max(var_x)).data
    if max_x > min_x:
        step = (max_x - min_x) / bins
        steps = torch.arange(
            min_x, max_x + step / 10, step
        ).to(var_x.device)
        h = map(
            lambda (min_i, max_i): torch.sum(
                (var_x >= min_i) & (var_x < max_i)
            ),
            zip(steps[:-1], steps[1:])
        )
        torch_h = torch.tensor(h).type(torch.float32).to(var_x.device)
        if norm:
            torch_h = torch_h / torch.sum(torch_h)
        return torch_h
    else:
        return None


def torch_hist2(var_x, var_y, bins=100, norm=True):
    """
        Function that computes a 2D histogram using two torch tensor.
        :param var_x: First tensor.
        :param var_y: Second tensor.
        :param bins: Number of bins for the histogram.
        :param norm: Whether or not to normalise the histogram. It is useful
        to define a joint probability density function of both variables.
        :return: A tensor with the histogram
    """
    min_x = torch.floor(torch.min(var_x)).data
    max_x = torch.ceil(torch.max(var_x)).data
    min_y = torch.floor(torch.min(var_y)).data
    max_y = torch.ceil(torch.max(var_y)).data
    if max_x > min_x and max_y > min_y:
        step_x = (max_x - min_x) / bins
        step_y = (max_y - min_y) / bins
        steps_x = torch.arange(
            min_x, max_x + step_x / 10, step_x
        ).to(var_x.device)
        steps_y = torch.arange(
            min_y, max_y + step_y / 10, step_y
        ).to(var_y.device)
        min_steps = product(steps_x[:-1], steps_y[:-1])
        max_steps = product(steps_x[1:], steps_y[1:])
        h = map(
            lambda ((min_i, min_j), (max_i, max_j)): torch.sum(
                (var_x >= min_i) & (var_x < max_i) &
                (var_y >= min_j) & (var_y < max_j)
            ),
            zip(min_steps, max_steps)
        )
        torch_h2 = torch.tensor(h).type(torch.float32).to(var_x.device)
        if norm:
            torch_h2 = torch_h2 / torch.sum(torch_h2)
        return torch_h2
    else:
        return None


def histogram_loss(var_x, var_y):
    """
        Loss function based on the histogram of the expected and predicted values.
        :param var_x: Predicted values.
        :param var_y: Expected values.
        :return: A tensor with the loss
    """
    # Histogram computation
    loss = 1
    hist_x = torch_hist(var_x)
    if hist_x is not None:
        hist_x = hist_x / torch.sum(hist_x)

        hist_y = torch_hist(var_y)
        if hist_y is not None:
            loss = torch.sum(torch.abs(hist_x - hist_y)) / 2

    return loss


def dsc_bin_loss(var_x, var_y):
    """
        Loss function for the binary dice loss. There is no need to binarise
         the tensors. In fact, we cast the target values to float (for the
         gradient).
        :param var_x: Predicted values.
        :param var_y: Expected values.
        :return: A tensor with the loss
    """
    var_y = var_y.type_as(var_x)
    intersection = torch.sum(var_x * var_y)
    sum_x = torch.sum(var_x)
    sum_y = torch.sum(var_y)
    sum_vals = sum_x + sum_y
    dsc_value = (2 * intersection / sum_vals) if sum_vals > 0 else 1.0
    return 1.0 - dsc_value


def gradient_mean(tensor, mask):
    """
        Function to compute the mean gradient of a multidimensional tensor. We
         assume that the first two dimensions specify the number of samples and
         channels.
        :param tensor: Input tensor
        :param mask: Mask that defines the region of interest where the loss
         should be evaluated.
        :return: The mean gradient tensor
    """

    # Init
    tensor_dims = len(tensor.shape)
    data_dims = tensor_dims - 2

    # Since we want this function to be generic, we need a trick to define
    # the gradient on each dimension.
    all_slices = (slice(0, None),) * (tensor_dims - 1)
    first = slice(0, -2)
    last = slice(2, None)
    slices = map(
        lambda i: (
            all_slices[:i + 2] + (first,) + all_slices[i + 2:],
            all_slices[:i + 2] + (last,) + all_slices[i + 2:],
        ),
        range(data_dims)
    )

    # Remember that gradients moved the image 0.5 pixels while also reducing
    # 1 voxel per dimension. To deal with that we are technically interpolating
    # the gradient in between these positions. These is the equivalent of
    # computing the gradient between voxels separated one space. 1D ex:
    # [a, b, c, d] -> gradient0.5 = [a - b, b - c, c - d]
    # gradient1 = 0.5 * [(a - b) + (b - c), (b - c) + (c - d)] = [a - c, b - d]
    no_pad = (0, 0)
    pad = (1, 1)
    paddings = map(
        lambda i: no_pad * i + pad + no_pad * (data_dims - i - 1),
        range(data_dims)[::-1]
    )

    gradients = map(
        lambda (p, (si, sf)): 0.5 * F.pad(tensor[si] - tensor[sf], p),
        zip(paddings, slices)
    )
    gradients = torch.cat(gradients, dim=1)

    mod_gradients = torch.sum(gradients * gradients, dim=1, keepdim=True)
    # no_pad = (0, 0)
    # pre_pad = (1, 0)
    # post_pad = (0, 1)
    #
    # pre_paddings = map(
    #     lambda i: no_pad * i + pre_pad + no_pad * (data_dims - i - 1),
    #     range(data_dims)[::-1]
    # )
    # post_paddings = map(
    #     lambda i: no_pad * i + post_pad + no_pad * (data_dims - i - 1),
    #     range(data_dims)[::-1]
    # )
    #
    # pre_padded = map(
    #     lambda (g, pad): F.pad(g, pad),
    #     zip(gradients, pre_paddings)
    # )
    # post_padded = map(
    #     lambda (g, pad): F.pad(g, pad),
    #     zip(gradients, post_paddings)
    # )
    #
    # pre_gradient = torch.cat(pre_padded, dim=1)
    # post_gradient = torch.cat(post_padded, dim=1)
    #
    # pre_mod = torch.sum(pre_gradient * pre_gradient, dim=1, keepdim=True)
    # post_mod = torch.sum(post_gradient * post_gradient, dim=1, keepdim=True)
    #
    # mean_grad = torch.mean(pre_mod[mask] + post_mod[mask])
    mean_grad = torch.mean(mod_gradients[mask])

    return mean_grad


def df_modulo(df, mask):
    """
        Loss function to maximise the modulo of the deformation field. I first
         implemented it thinking it would help to get large deformations, but
         it doesn't seem to be necessary. In order to maximise, I am using the
         negative value of the modulo (avoiding the square root) and an
         exponential function. That might promote extremely large deformations.
        :param df: A deformation field tensor.
        :param mask: Mask that defines the region of interest where the loss
         should be evaluated.
        :return: The mean modulo tensor
    """
    modulo = torch.sum(df * df, dim=1, keepdim=True)
    mean_grad = torch.mean(torch.exp(-modulo[mask]))

    return mean_grad
