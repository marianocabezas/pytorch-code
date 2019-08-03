from __future__ import division
import itertools
import numpy as np
import torch
from torch.utils.data.dataset import Dataset
from torch.utils.data.sampler import Sampler
from scipy.ndimage.morphology import binary_erosion as imerode
from data_manipulation.generate_features import get_mask_voxels
from numpy import logical_not as log_not
from numpy import logical_and as log_and
from numpy import logical_or as log_or


def get_slices_bb(
        masks, patch_size, overlap, filtered=False, min_size=0
):
    patch_half = map(lambda p_length: p_length // 2, patch_size)
    steps = map(lambda p_length: max(p_length - overlap, 1), patch_size)

    if type(masks) is list:
        min_bb = map(lambda mask: np.min(np.where(mask > 0), axis=-1), masks)
        min_bb = map(
            lambda min_bb_i: map(
                lambda (min_i, p_len): min_i + p_len,
                zip(min_bb_i, patch_half)
            ),
            min_bb
        )
        max_bb = map(lambda mask: np.max(np.where(mask > 0), axis=-1), masks)
        max_bb = map(
            lambda max_bb_i: map(
                lambda (max_i, p_len): max_i - p_len,
                zip(max_bb_i, patch_half)
            ),
            max_bb
        )

        dim_ranges = map(
            lambda (min_bb_i, max_bb_i): map(
                lambda t: np.concatenate([np.arange(*t), [t[1]]]),
                zip(min_bb_i, max_bb_i, steps)
            ),
            zip(min_bb, max_bb)
        )

        patch_slices = map(
            lambda dim_range: centers_to_slice(
                itertools.product(*dim_range), patch_half
            ),
            dim_ranges
        )

        if filtered:
            patch_slices = map(
                lambda (slices, mask): filter_size(slices, mask, min_size),
                zip(patch_slices, masks)
            )

    else:
        # Create bounding box and define
        min_bb = np.min(np.where(masks > 0), axis=-1)
        min_bb = map(
            lambda (min_i, p_len): min_i + p_len,
            zip(min_bb, patch_half)
        )
        max_bb = np.max(np.where(masks > 0), axis=-1)
        max_bb = map(
            lambda (max_i, p_len): max_i - p_len,
            zip(max_bb, patch_half)
        )

        dim_range = map(lambda t: np.arange(*t), zip(min_bb, max_bb, steps))
        patch_slices = centers_to_slice(
            itertools.product(*dim_range), patch_half
        )

        if filtered:
            patch_slices = filter_size(patch_slices, masks, min_size)

    return patch_slices


def get_slices_boundary(
        masks, patch_size, rois=None, rate=0.1
):
    patch_half = map(lambda p_length: p_length // 2, patch_size)
    boundaries = map(
        lambda m: map(
            lambda l: log_and(m == l, log_not(imerode(m == l))),
            range(1, m.max() + 1)
        ),
        masks
    )

    max_shape = masks[0].shape
    mesh = get_mesh(max_shape)
    legal_mask = reduce(
            np.logical_and,
            map(
                lambda (m_j,  p_ij, max_j): np.logical_and(
                    m_j >= p_ij,
                    m_j <= max_j - p_ij
                ),
                zip(mesh, patch_half, max_shape)
            )
    )

    boundaries = map(
        lambda b: map(
            lambda b_i: np.logical_and(b_i, legal_mask), b
        ),
        boundaries
    )

    centers = map(
        lambda b: np.concatenate(
            filter(
                lambda arr: arr.size > 0,
                map(
                    lambda b_i: np.random.permutation(
                        zip(*np.where(b_i))
                    )[:int(np.sum(b_i) * rate)],
                    b
                )
            ),
            axis=0
        ),
        boundaries
    )

    patch_slices = map(lambda c: centers_to_slice(c, patch_half), centers)

    return patch_slices


def centers_to_slice(voxels, patch_half):
    slices = map(
        lambda voxel: tuple(
            map(
                lambda (idx, p_len): slice(idx - p_len, idx + p_len),
                zip(voxel, patch_half)
            )
        ),
        voxels
    )
    return slices


def filter_size(slices, mask, min_size):
    filtered_slices = filter(
        lambda s_i: np.sum(mask[s_i] > 0) > min_size, slices
    )

    return filtered_slices


def get_balanced_slices(
        masks, patch_size, rois=None, min_size=0,
        neg_ratio=1
):
    # Init
    patch_half = map(lambda p_length: p_length // 2, patch_size)

    # Bounding box + not mask voxels
    if rois is None:
        min_bb = map(lambda mask: np.min(np.where(mask > 0), axis=-1), masks)
        max_bb = map(lambda mask: np.max(np.where(mask > 0), axis=-1), masks)
        bck_masks = map(np.logical_not, masks)
    else:
        min_bb = map(lambda mask: np.min(np.where(mask > 0), axis=-1), rois)
        max_bb = map(lambda mask: np.max(np.where(mask > 0), axis=-1), rois)
        bck_masks = map(
            lambda (m, roi): np.logical_and(m, roi.astype(bool)),
            zip(map(np.logical_not, masks), rois)
        )

    # The idea with this is to create a binary representation of illegal
    # positions for possible patches. That means positions that would create
    # patches with a size smaller than patch_size.
    # For notation, i = case; j = dimension
    max_shape = masks[0].shape
    mesh = get_mesh(max_shape)
    legal_masks = map(
        lambda (min_i, max_i): reduce(
            np.logical_and,
            map(
                lambda (m_j, min_ij, max_ij, p_ij, max_j): np.logical_and(
                    m_j >= max(min_ij, p_ij),
                    m_j <= min(max_ij, max_j - p_ij)
                ),
                zip(mesh, min_i, max_i, patch_half, max_shape)
            )
        ),
        zip(min_bb, max_bb)
    )

    # Filtering with the legal mask
    fmasks = map(
        lambda (m_i, l_i): np.logical_and(m_i, l_i), zip(masks, legal_masks)
    )
    fbck_masks = map(
        lambda (m_i, l_i): np.logical_and(m_i, l_i), zip(bck_masks, legal_masks)
    )

    lesion_voxels = map(get_mask_voxels, fmasks)
    bck_voxels = map(get_mask_voxels, fbck_masks)

    lesion_slices = map(
        lambda vox: centers_to_slice(vox, patch_half), lesion_voxels
    )

    if min_size > 0:
        bck_slices = map(
            lambda vox: centers_to_slice(vox, patch_half), bck_voxels
        )

        # Minimum size filtering for background
        fbck_slices = map(
            lambda (slices, mask): filter_size(slices, mask, min_size),
            zip(bck_slices, masks)
        )

        # Final slice selection
        patch_slices = map(
            lambda (pos_s, neg_s): pos_s + map(
                lambda idx: neg_s[idx],
                np.random.permutation(
                    len(neg_s)
                )[:int(neg_ratio * len(pos_s))]
            ),
            zip(lesion_slices, fbck_slices)
        )

    else:
        fbck_slices = map(
            lambda (lvox, bvox): centers_to_slice(
                map(
                    lambda idx: bvox[idx],
                    np.random.permutation(
                        len(bvox)
                    )[:int(neg_ratio * len(lvox))]
                ),
                patch_half
            ),
            zip(lesion_voxels, bck_voxels)
        )

        # Final slice selection
        patch_slices = map(
            lambda (pos_s, neg_s): pos_s + neg_s,
            zip(lesion_slices, fbck_slices)
        )

    return patch_slices


def get_mesh(shape):
    linvec = tuple(map(lambda s: np.linspace(0, s - 1, s), shape))
    mesh = np.stack(np.meshgrid(*linvec, indexing='ij')).astype(np.float32)
    return mesh


class GenericSegmentationCroppingDataset(Dataset):
    def __init__(
            self,
            cases, labels=None, masks=None, balanced=True, overlap=0,
            min_size=0, patch_size=32, neg_ratio=1, sampler=False,
    ):
        # Init
        self.neg_ratio = neg_ratio
        # Image and mask should be numpy arrays
        self.sampler = sampler
        self.cases = cases
        self.labels = labels

        self.masks = masks

        data_shape = self.cases[0].shape

        if type(patch_size) is not tuple:
            patch_size = (patch_size,) * len(data_shape)
        self.patch_size = patch_size

        self.patch_slices = []
        if balanced:
            if self.masks is not None:
                self.patch_slices = get_balanced_slices(
                    self.labels, self.patch_size, self.masks,
                    neg_ratio=self.neg_ratio
                )
            elif self.labels is not None:
                self.patch_slices = get_balanced_slices(
                    self.labels, self.patch_size, self.labels,
                    neg_ratio=self.neg_ratio
                )
            else:
                data_single = map(
                    lambda d: np.ones_like(
                        d[0] if len(d) > 1 else d
                    ),
                    self.cases
                )
                self.patch_slices = get_slices_bb(data_single, self.patch_size, 0)
        else:
            if self.masks is not None:
                self.patch_slices = get_slices_bb(
                    self.masks, self.patch_size, overlap=overlap,
                    min_size=min_size, filtered=True
                )
            elif self.labels is not None:
                self.patch_slices = get_slices_bb(
                    self.labels, self.patch_size, overlap=overlap,
                    min_size=min_size, filtered=True
                )
            else:
                data_single = map(
                    lambda d: np.ones_like(
                        d[0] > np.min(d[0]) if len(d) > 1 else d
                    ),
                    self.cases
                )
                self.patch_slices = get_slices_bb(
                    data_single, self.patch_size, overlap=overlap,
                    min_size=min_size, filtered=True
                )
        self.max_slice = np.cumsum(map(len, self.patch_slices))

    def __getitem__(self, index):
        # We select the case
        case_idx = np.min(np.where(self.max_slice > index))
        case = self.cases[case_idx]

        slices = [0] + self.max_slice.tolist()
        patch_idx = index - slices[case_idx]
        case_slices = self.patch_slices[case_idx]

        # We get the slice indexes
        none_slice = (slice(None, None),)
        slice_i = case_slices[patch_idx]

        inputs = case[none_slice + slice_i].astype(np.float32)

        if self.labels is not None:
            labels = self.labels[case_idx].astype(np.uint8)
            target = np.expand_dims(labels[slice_i], 0)

            if self.sampler:
                return inputs, target, index
            else:
                return inputs, target
        else:
            return inputs, case_idx, slice_i

    def __len__(self):
        return self.max_slice[-1]


class BoundarySegmentationCroppingDataset(Dataset):
    def __init__(self, cases, labels=None, masks=None, patch_size=32):
        # Init
        # Image and mask should be numpy arrays
        self.cases = cases
        self.labels = labels

        self.masks = masks

        data_shape = self.cases[0].shape

        if type(patch_size) is not tuple:
            patch_size = (patch_size,) * len(data_shape)
        self.patch_size = patch_size

        if self.masks is not None:
            self.patch_slices = get_slices_boundary(
                self.labels, self.patch_size, self.masks,
            )
        elif self.labels is not None:
            self.patch_slices = get_slices_boundary(
                self.labels, self.patch_size, self.labels,
            )
        else:
            data_single = map(
                lambda d: np.ones_like(
                    d[0] if len(d) > 1 else d
                ),
                self.cases
            )
            self.patch_slices = get_slices_boundary(data_single, self.patch_size)
        self.max_slice = np.cumsum(map(len, self.patch_slices))

    def __getitem__(self, index):
        # We select the case
        case_idx = np.min(np.where(self.max_slice > index))
        case = self.cases[case_idx]

        slices = [0] + self.max_slice.tolist()
        patch_idx = index - slices[case_idx]
        case_slices = self.patch_slices[case_idx]

        # We get the slice indexes
        none_slice = (slice(None, None),)
        slice_i = case_slices[patch_idx]

        inputs = case[none_slice + slice_i].astype(np.float32)

        if self.labels is not None:
            labels = self.labels[case_idx].astype(np.uint8)
            target = np.expand_dims(labels[slice_i], 0)

            return inputs, target
        else:
            return inputs, case_idx, slice_i

    def __len__(self):
        return self.max_slice[-1]


class BBImageDataset(Dataset):
    def __init__(
            self,
            cases, labels, masks, sampler=False, mode=None, flip=False,
    ):
        # Init
        # Image and mask should be numpy arrays
        self.sampler = sampler
        self.cases = cases
        self.labels = labels
        self.flip = flip

        self.masks = masks

        indices = map(lambda mask: np.where(mask > 0), self.masks)

        if mode is None:
            self.bb = map(
                lambda idx: map(
                    lambda (min_i, max_i): slice(min_i, max_i),
                    zip(np.min(idx, axis=-1), np.max(idx, axis=-1))
                ),
                indices
            )
        elif mode is 'min':
            min_bb = np.max(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            max_bb = np.min(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            self.bb = map(
                lambda (min_i, max_i): slice(min_i, max_i),
                zip(min_bb, max_bb)
            ),
        elif mode is 'max':
            min_bb = np.min(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            max_bb = np.max(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            self.bb = map(
                lambda (min_i, max_i): slice(min_i, max_i),
                zip(min_bb, max_bb)
            ),

    def __getitem__(self, index):
        if len(self.bb) == len(self.cases):
            bb = self.bb[index]
        else:
            bb = self.bb

        if self.flip:
            inputs = self.cases[index // 2][tuple([slice(None)] + bb)]
            if (index % 2) == 1:
                inputs = np.fliplr(inputs).copy()
        else:
            inputs = self.cases[index][tuple([slice(None)] + bb)]

        if self.labels is not None:
            if self.flip:
                targets = self.labels[index // 2][tuple(bb)]
                if (index % 2) == 1:
                    targets = np.flipud(targets).copy()

            else:
                targets = self.labels[index][tuple(bb)]

            np.expand_dims(targets, axis=0)

            if self.sampler:
                return inputs, targets, index
            else:
                return inputs, targets
        else:
            return inputs

    def __len__(self):
        return len(self.cases) * 2 if self.flip else len(self.cases)


class BBImageValueDataset(Dataset):
    def __init__(
            self,
            cases, values, masks, sampler=False, mode='max',
    ):
        # Init
        # Image and mask should be numpy arrays
        self.sampler = sampler
        self.cases = cases
        self.values = values

        self.masks = masks

        indices = map(lambda mask: np.where(mask > 0), self.masks)

        if mode is None:
            self.bb = map(
                lambda idx: map(
                    lambda (min_i, max_i): slice(min_i, max_i),
                    zip(np.min(idx, axis=-1), np.max(idx, axis=-1))
                ),
                indices
            )
        elif mode is 'min':
            min_bb = np.max(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            max_bb = np.min(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            self.bb = map(
                lambda (min_i, max_i): slice(min_i, max_i),
                zip(min_bb, max_bb)
            ),
        elif mode is 'max':
            min_bb = np.min(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            max_bb = np.max(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            self.bb = map(
                lambda (min_i, max_i): slice(min_i, max_i),
                zip(min_bb, max_bb)
            ),

    def __getitem__(self, index):
        if len(self.bb) == len(self.cases):
            bb = self.bb[index]
        else:
            bb = self.bb

        inputs = self.cases[index][tuple([slice(None)] + bb)]

        if self.values is not None:
            targets = np.expand_dims(self.values[index], axis=0)

            if self.sampler:
                return inputs, targets, index
            else:
                return inputs, targets
        else:
            return inputs

    def __len__(self):
        return len(self.cases)


class BBImageTupleDataset(Dataset):
    def __init__(
            self,
            cases, labels, masks, mode=None,
    ):
        # Init
        # Image and mask should be numpy arrays
        self.cases = cases
        self.labels = labels

        self.masks = masks

        indices = map(lambda mask: np.where(mask > 0), self.masks)

        self.labels_mix = map(
            lambda (l, r):  (l > 0).astype(int) + (r > 0).astype(int),
            zip(self.labels, self.masks)
        )

        if mode is None:
            self.bb = map(
                lambda idx: map(
                    lambda (min_i, max_i): slice(min_i, max_i),
                    zip(np.min(idx, axis=-1), np.max(idx, axis=-1))
                ),
                indices
            )
        elif mode is 'min':
            min_bb = np.max(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            max_bb = np.min(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            self.bb = map(
                lambda (min_i, max_i): slice(min_i, max_i),
                zip(min_bb, max_bb)
            ),
        elif mode is 'max':
            min_bb = np.min(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            max_bb = np.max(
                map(
                    lambda idx: np.min(idx, axis=-1),
                    indices
                ),
                axis=0
            )
            self.bb = map(
                lambda (min_i, max_i): slice(min_i, max_i),
                zip(min_bb, max_bb)
            ),

    def __getitem__(self, index):
        if len(self.bb) == len(self.cases):
            bb = self.bb[index]
        else:
            bb = self.bb

        inputs = self.cases[index][tuple([slice(None)] + bb)]

        targets = (
            np.expand_dims(self.labels[index][tuple(bb)], axis=0),
            np.expand_dims(self.labels_mix[index][tuple(bb)], axis=0)
        )

        return inputs, targets

    def __len__(self):
        return len(self.cases)


def sample(weights, want):
    have = 0
    samples = torch.empty(want, dtype=torch.long)
    while have < want:
        a = torch.multinomial(weights, want - have, replacement=True)
        b = a.unique()
        samples[have:have + b.size(-1)] = b
        weights[b] = 0
        have += b.size(-1)

    return samples


class WeightedSubsetRandomSampler(Sampler):

    def __init__(
            self,
            num_samples, sample_div=2,
            initial_rate=0.1, rate_increase=0.05,
            *args
    ):
        super(WeightedSubsetRandomSampler, self).__init__(args)
        self.step = 0
        self.step_inc = sample_div
        self.rate = initial_rate
        self.rate_increase = rate_increase
        self.total_samples = num_samples
        self.num_samples = int(np.ceil(num_samples / sample_div))
        self.weights = torch.tensor(
            [np.iinfo(np.int16).max] * num_samples, dtype=torch.double
        )
        self.initial = torch.randperm(num_samples)
        self.indices = self.initial[:self.num_samples]

    def __iter__(self):
        return (i for i in self.indices.tolist())

    def __len__(self):
        return self.num_samples

    def update_weights(self, weights, idx):
        self.weights[idx] = weights.type_as(self.weights)

    def update(self):
        # We want to ensure that during the first sampling stages we use the
        # whole dataset. After that, we will begin sampling a percentage of
        # the worst samples.
        self.step += 1
        if self.step < self.step_inc:
            idx_ini = self.step * self.num_samples
            idx_end = (self.step + 1) * self.num_samples
            self.indices = self.initial[idx_ini:idx_end]
        else:
            n_hard = int(self.num_samples * self.rate)
            n_easy = self.num_samples - n_hard

            # Here we actually collect either the hard samples, or the initial
            # ones (which will always have a high weight, until used for training.
            max_w = torch.max(self.weights)
            easy_w = torch.clamp(max_w - self.weights, 0, max_w)
            easy_idx = sample(easy_w, n_easy)
            hard_w = self.weights.clone()
            hard_w[easy_idx] = 0
            hard_idx = sample(hard_w, n_hard)
            mixed_indices = torch.cat((hard_idx, easy_idx))
            self.indices = mixed_indices[torch.randperm(len(mixed_indices))]

        # This part is to increase the percentage of "bad samples". The idea
        # is to introduce them slowly, so that the classifier doesn't become
        # unstable. Right now, the number of steps needed is fixed, but I might
        # introduce a parameter for it.
        if self.step > self.step_inc and (self.step % self.step_inc) == 0:
            self.rate = min(self.rate + self.rate_increase, 1)


class WeightedSplitRandomSampler(Sampler):

    def __init__(
            self,
            num_samples, sample_div=2, splits=10, *args
    ):
        super(WeightedSplitRandomSampler, self).__init__(args)
        self.step = 0
        self.divs = sample_div
        self.splits = splits
        self.total_samples = num_samples
        self.num_samples = num_samples // sample_div
        self.weights = torch.tensor(
            [np.iinfo(np.int16).max] * num_samples, dtype=torch.double
        )
        self.initial = torch.randperm(num_samples)
        self.indices = self.initial[:self.num_samples]

    def __iter__(self):
        return (i for i in self.indices.tolist())

    def __len__(self):
        return self.num_samples

    def update_weights(self, weights, idx):
        self.weights[idx] = weights.type_as(self.weights)

    def update(self):
        # We want to ensure that during the first sampling stages we use the
        # whole dataset. After that, we will begin sampling a percentage of
        # the worst samples.
        if self.step < self.divs:
            idx_ini = (self.step + 1) * self.num_samples
            idx_end = (self.step + 2) * self.num_samples
            self.indices = self.initial[idx_ini:idx_end]
        else:
            ordered_idx = torch.argsort(self.weights)
            # TODO: Fix this, please...
            good_idx = ordered_idx[:len(ordered_idx) // 2]
            good_idx = good_idx[torch.randperm(len(good_idx))]
            good_idx = good_idx[self.num_samples // 2]
            bad_idx = ordered_idx[len(ordered_idx) // 2:]
            good_idx = good_idx[torch.randperm(len(bad_idx))]
            good_idx = good_idx[self.num_samples - self.num_samples // 2]
            self.indices = torch.cat(
                (good_idx, bad_idx)
            )[torch.randperm(self.samples)]
        self.step += 1
